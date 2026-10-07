#!/usr/bin/env python3
"""Install the immutable origin configuration with atomic files and a retained receipt."""

import argparse
import hashlib
import json
import os
import re
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


def source_provenance() -> dict:
    """Keep immutable release identity separate from staged source validation."""
    values = {
        "source_commit": os.environ.get("ORIGIN_SOURCE_COMMIT"),
        "archive_sha256": os.environ.get("ORIGIN_ARCHIVE_SHA256"),
        "installer_sha256": os.environ.get("ORIGIN_INSTALLER_SHA256"),
    }
    if all(value is None for value in values.values()):
        return {"source_kind": "staged"}
    if any(
        not isinstance(value, str)
        or not re.fullmatch(
            "[a-f0-9]{" + str(40 if key == "source_commit" else 64) + "}", value
        )
        for key, value in values.items()
    ):
        message = "immutable origin source provenance missing or malformed"
        raise ValueError(message)
    return {"source_kind": "immutable-release", **values}


def main() -> int:
    """Stage configuration and provision only when explicitly selected."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--provision", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    from render_origin import render  # noqa: PLC0415, I001  # pylint: disable=import-outside-toplevel

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
    files.append(
        {
            "path": "/usr/local/bin/crapi_signup_cleanup.py",
            "content": (source / "scripts/crapi_signup_cleanup.py").read_text(),
        }
    )
    for name, target in [
        ("catalog_signup_recovery.py", "catalog-signup-recovery"),
        ("enroll_signup_recovery.py", "enroll-signup-recovery"),
    ]:
        files.append(
            {
                "path": "/usr/local/bin/" + target,
                "permissions": "0755",
                "content": (source / "scripts" / name).read_text(),
            }
        )
    files.append(
        {
            "path": "/usr/local/bin/application_receipts.py",
            "content": (source / "scripts/application_receipts.py").read_text(),
        }
    )
    files.append(
        {
            "path": "/usr/local/bin/origin-verify-workflows",
            "permissions": "0755",
            "content": (source / "scripts/verify_workflows.py").read_text(),
        }
    )
    files.append(
        {
            "path": "/usr/local/bin/origin-verify-crapi-browser.mjs",
            "permissions": "0755",
            "content": (source / "scripts/verify_crapi_browser.mjs").read_text(),
        }
    )
    for name in ("Dockerfile", "package.json", "package-lock.json"):
        files.append(
            {
                "path": "/opt/origin-server/browser-runtime/" + name,
                "content": (source / "provisioning/browser-runtime" / name).read_text(),
            }
        )
    for name in (
        "verify_content.mjs",
        "verify_crapi_browser.mjs",
        "verify_juice_browser.mjs",
        "verify_dvwa_browser.mjs",
        "verify_dvga_browser.mjs",
        "verify_csd_browser.mjs",
        "verify_restaurant_browser.mjs",
        "verify_httpbin_browser.mjs",
        "verify_crapi_signup.mjs",
    ):
        files.append(
            {
                "path": "/opt/origin-server/browser-runtime/" + name,
                "content": (source / "scripts" / name).read_text(),
            }
        )
    files.append(
        {
            "path": "/usr/local/bin/origin-browser-verify",
            "permissions": "0755",
            "content": (source / "scripts/browser_runtime.py").read_text(),
        }
    )
    for name, source_file in (
        ("catalog-order-recovery", "catalog_order_recovery.py"),
        ("catalog-family-recovery", "catalog_family_recovery.py"),
        ("enroll-family-recovery", "enroll_signup_recovery.py"),
        ("enroll-order-recovery", "enroll_signup_recovery.py"),
    ):
        files.append(
            {
                "path": "/usr/local/bin/" + name,
                "permissions": "0755",
                "content": (source / "scripts" / source_file).read_text(),
            }
        )
    files.append(
        {
            "path": "/usr/local/bin/catalog_dvwa_recovery.py",
            "permissions": "0644",
            "content": (source / "scripts/catalog_dvwa_recovery.py").read_text(),
        }
    )
    files.append(
        {
            "path": "/usr/local/bin/catalog_restaurant_recovery.py",
            "permissions": "0644",
            "content": (source / "scripts/catalog_restaurant_recovery.py").read_text(),
        }
    )
    files.append(
        {
            "path": "/opt/origin-server/juice-shop-framing/catalog-journal.cjs",
            "permissions": "0644",
            "content": (source / "scripts/juice_catalog_journal.cjs").read_text(),
        }
    )
    files.append(
        {
            "path": "/usr/local/bin/catalog_juice_recovery.py",
            "permissions": "0644",
            "content": (source / "scripts/catalog_juice_recovery.py").read_text(),
        }
    )
    receipt = {
        **source_provenance(),
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
