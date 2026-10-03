#!/usr/bin/env python3
"""Run locked browser verification with private evidence and owned container cleanup."""

import argparse
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path


def evidence_directory(path: Path) -> Path:
    """Reject symlink evidence destinations before resolving them."""
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        message = "private evidence path cannot traverse a symlink"
        raise ValueError(message)
    output = path.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    return output


def cleanup_container(name: str, marker: str) -> None:
    """A name alone cannot authorize removal of a foreign browser container."""
    result = subprocess.run(  # noqa: S603 - exact task-owned container lookup
        ["/usr/bin/docker", "inspect", name, "--format", "{{json .}}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode:
        return
    container = json.loads(result.stdout)
    if (
        container.get("Name") != "/" + name
        or container.get("Config", {}).get("Labels", {}).get("org.f5.demo.verifier")
        != marker
    ):
        message = "browser container ownership mismatch"
        raise ValueError(message)
    subprocess.run(  # noqa: S603 - verified exact owned container
        ["/usr/bin/docker", "rm", "--force", name],
        capture_output=True,
        check=True,
        timeout=30,
    )


def evidence_size(root: Path) -> int:
    """Count regular private evidence while concurrent atomic writers rename files."""
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except FileNotFoundError:
            continue
    return total


def retain_evidence(
    root: Path, active: Path, days: int = 7, max_bytes: int = 10 * 1024**3
) -> None:
    """Evict completed owned browser evidence without touching active or unrelated work."""
    candidates = []
    for directory in root.glob("private-browser-*"):
        if directory == active or directory.is_symlink() or not directory.is_dir():
            continue
        try:
            receipt = json.loads((directory / "runtime-receipt.json").read_text())
            if receipt.get("cleanup") is True:
                candidates.append(directory)
        except (OSError, ValueError):
            continue
    total = sum(evidence_size(directory) for directory in [active, *candidates])
    for directory in sorted(candidates, key=lambda path: path.stat().st_mtime):
        if time.time() - directory.stat().st_mtime > days * 86400 or total > max_bytes:
            size = evidence_size(directory)
            shutil.rmtree(directory)
            total -= size


def main() -> int:
    """Retain timeout and tool failures without leaving Chromium running."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "kind",
        choices=("content", "crapi", "juice", "dvwa", "dvga", "csd", "restaurant"),
    )
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    if args.native and args.kind not in ("dvwa", "dvga", "csd"):
        parser.error(
            "native browser routing is currently supported only for DVWA, DVGA and CSD"
        )
    output = evidence_directory(args.output)
    retain_evidence(output.parent, output)
    marker = uuid.uuid4().hex
    name = "origin-browser-" + marker
    source = "/opt/origin-server/browser-runtime"
    script = {
        "content": "verify_content.mjs",
        "crapi": "verify_crapi_browser.mjs",
        "juice": "verify_juice_browser.mjs",
        "dvwa": "verify_dvwa_browser.mjs",
        "dvga": "verify_dvga_browser.mjs",
        "csd": "verify_csd_browser.mjs",
        "restaurant": "verify_restaurant_browser.mjs",
    }[args.kind]
    arguments = (
        ["--manifest", "/manifest.json", "--base", args.base, "--output", "/evidence"]
        if args.kind == "content"
        else [args.base, "/evidence"]
    )
    if args.native:
        arguments.append("/")
    command = [
        "/usr/bin/docker",
        "run",
        "--rm",
        "--name",
        name,
        "--label",
        "org.f5.demo.verifier=" + marker,
        "--network",
        "host",
        "--shm-size",
        "1g",
        "--memory",
        "2g",
        "--cpus",
        "2",
        "--volume",
        str(output) + ":/evidence",
        "--volume",
        source + ":/opt/origin-browser/source:ro",
        "--volume",
        "/opt/origin-server/applications.json:/manifest.json:ro",
        "origin-browser-verifier",
        "node",
        "/opt/origin-browser/source/" + script,
        *arguments,
    ]
    provenance = json.loads(Path("/opt/origin-server/install-receipt.json").read_text())
    receipt = {
        "started": time.time(),
        "status": "running",
        "cleanup": False,
        "source_commit": provenance.get("source_commit"),
        "native": args.native,
        "archive_sha256": provenance.get("archive_sha256"),
    }
    code = 1
    try:
        with subprocess.Popen(command) as process:  # noqa: S603 - exact locked runtime argv
            deadline = time.monotonic() + 900
            while process.poll() is None:
                retain_evidence(output.parent, output)
                if evidence_size(output) > 10 * 1024**3:
                    process.terminate()
                    receipt.update(status="failed", reason="evidence-cap")
                    break
                if time.monotonic() >= deadline:
                    process.terminate()
                    receipt.update(status="failed", reason="browser-timeout")
                    break
                time.sleep(0.5)
            code = process.wait(timeout=30)

        receipt.update(status="completed" if code == 0 else "failed", exit_code=code)
    except subprocess.TimeoutExpired:
        code = 124
        receipt.update(status="failed", reason="browser-timeout", exit_code=code)
    finally:
        cleanup_container(name, marker)
        receipt.update(completed=time.time(), cleanup=True)
        path = output / "runtime-receipt.json"
        path.write_text(json.dumps(receipt))
        path.chmod(0o600)
        retain_evidence(output.parent, output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
