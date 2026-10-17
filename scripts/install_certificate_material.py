#!/usr/bin/env python3
"""Atomically install machine-encrypted TLS credentials and remove private staging."""

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


def install(stage: Path) -> None:
    """Consume one protected upload directory under the authenticated owner's home."""
    if os.geteuid() != 0 or stage.is_symlink() or stage.parent.is_symlink():
        message = "Native root and a protected staging directory are required"
        raise ValueError(message)
    if stage.name != ".origin-certificate-upload" or stage.stat().st_mode & 0o077:
        message = "Certificate upload directory is not owner-only"
        raise ValueError(message)
    files = [stage / name for name in ["key.pem", "certificate.pem", "client-ca.pem"]]
    if any(
        path.is_symlink() or not stat.S_ISREG(path.stat().st_mode) for path in files
    ):
        message = "Certificate material must be regular owner-staged files"
        raise ValueError(message)
    key, certificate, client_ca = files
    key.chmod(0o600)
    destination = Path("/etc/credstore.encrypted")
    destination.mkdir(mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".origin-tls-", dir=destination)
    os.close(descriptor)
    encrypted = Path(temporary)
    encrypted.unlink()
    try:
        subprocess.run(  # noqa: S603 -- Fixed systemd tool and validated protected staging paths.
            [
                "/usr/bin/systemd-creds",
                "encrypt",
                "--with-key=host",
                "--name=tls_key",
                str(key),
                str(encrypted),
            ],
            check=True,
            capture_output=True,
        )
        encrypted.chmod(0o600)
        encrypted.replace(destination / "origin-tls-key")
        public = Path("/etc/origin-certificate")
        public.mkdir(mode=0o755, exist_ok=True)
        for source, name in [
            (certificate, "certificate.pem"),
            (client_ca, "client-ca.pem"),
        ]:
            target = public / name
            content = source.read_bytes()
            descriptor, temporary_public = tempfile.mkstemp(
                prefix=".origin-public-", dir=public
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            staged = Path(temporary_public)
            staged.chmod(0o644)
            staged.replace(target)
        subprocess.run(
            ["/usr/bin/systemctl", "daemon-reload"], check=True, capture_output=True
        )
        subprocess.run(
            ["/usr/bin/systemctl", "restart", "origin-certificate.service"],
            check=True,
            capture_output=True,
        )
    finally:
        encrypted.unlink(missing_ok=True)
        for path in files:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    install(Path(sys.argv[1]))
