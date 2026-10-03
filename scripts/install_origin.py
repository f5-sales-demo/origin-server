#!/usr/bin/env python3
"""Install the immutable origin configuration with atomic files and a retained receipt."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

ALLOWED_ROOTS = ("/etc/", "/opt/origin-server/", "/usr/local/", "/var/www/html/")


def install_files(files: list[dict], root: Path) -> None:
    """Validate every destination before atomically replacing configuration files."""
    root = root.resolve()
    destinations = []
    for item in files:
        path = item["path"]
        if not path.startswith(ALLOWED_ROOTS) or ".." in Path(path).parts:
            message = "installer destination escapes the origin configuration"
            raise ValueError(message)
        target = root / path.lstrip("/")
        if any(parent.is_symlink() for parent in (target, *target.parents)):
            message = "installer destination traverses a symlink"
            raise ValueError(message)
        if target in destinations:
            message = "duplicate installer destination"
            raise ValueError(message)
        destinations.append(target)
    for item, target in zip(files, destinations, strict=True):
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".origin-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(item["content"])
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary).chmod(int(item.get("permissions", "0644"), 8))
            Path(temporary).replace(target)
        finally:
            Path(temporary).unlink(missing_ok=True)


def require_native_root(root: Path) -> None:
    """Provision only the real guest filesystem under root privilege."""
    if root != Path("/") or os.geteuid() != 0:
        message = "provisioning requires the native root as root user"
        raise ValueError(message)


def main() -> int:
    """Stage configuration and provision only when explicitly selected."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--provision", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    from render_origin import render  # noqa: PLC0415 - CLI-only rendering dependency

    files = render(source)
    manifest = source / "provisioning/applications.json"
    files.extend(
        [
            {
                "path": "/opt/origin-server/applications.json",
                "content": manifest.read_text(),
            },
            {
                "path": "/usr/local/lib/origin/application_manifest.py",
                "content": (source / "scripts/application_manifest.py").read_text(),
            },
            {
                "path": "/usr/local/bin/origin-verify-content.mjs",
                "permissions": "0755",
                "content": (source / "scripts/verify_content.mjs").read_text(),
            },
        ]
    )
    receipt = {
        "started": time.time(),
        "status": "installing",
        "files_sha256": hashlib.sha256(
            (source / "provisioning/files.json").read_bytes()
        ).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    receipt_path = args.root / "opt/origin-server/install-receipt.json"
    install_files(files, args.root)
    previous = receipt_path.with_name("install-receipts")
    previous.mkdir(mode=0o700, exist_ok=True)
    if receipt_path.exists():
        previous.joinpath(str(time.time_ns()) + ".json").write_bytes(
            receipt_path.read_bytes()
        )
    receipt_path.write_text(json.dumps(receipt))
    receipt_path.chmod(0o600)
    try:
        if args.provision:
            require_native_root(args.root)
            subprocess.run(["/usr/local/bin/demo-origin-provision"], check=True)
        receipt.update(
            status="provisioned" if args.provision else "staged", completed=time.time()
        )
    except Exception:
        receipt.update(status="failed", completed=time.time())
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt))
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
