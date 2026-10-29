#!/usr/bin/env python3
"""Install exact checksum-verified Docker packages and verify native readback."""

import hashlib
import json
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

LOCK = Path("/opt/origin-server/docker-packages.json")


EXPECTED_PACKAGES = {
    "docker-ce",
    "docker-ce-cli",
    "containerd.io",
    "docker-buildx-plugin",
    "docker-compose-plugin",
}


def locked_records(lock: Path) -> list[dict]:
    """Reject malformed or incomplete package ownership before downloads or commands."""
    value = json.loads(lock.read_text())
    records = value.get("packages", [])
    if (
        value.get("schema_version") != 1
        or not isinstance(records, list)
        or len(records) != len(EXPECTED_PACKAGES)
    ):
        message = "invalid Docker package lock"
        raise ValueError(message)
    names = set()
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get("package") not in EXPECTED_PACKAGES
        ):
            message = "invalid Docker package lock identity"
            raise ValueError(message)
        names.add(record["package"])
        size = record.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            message = "invalid Docker package lock artifact size"
            raise ValueError(message)
        if (
            record.get("architecture") != "amd64"
            or not isinstance(record.get("version"), str)
            or not record["version"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))
        ):
            message = "invalid Docker package lock artifact"
            raise ValueError(message)
    if names != EXPECTED_PACKAGES:
        message = "incomplete Docker package lock"
        raise ValueError(message)
    return records


def download_package(record: dict, directory: Path) -> Path:
    """Verify immutable artifact bytes before any package manager action."""
    url = urllib.parse.urlsplit(record["url"])
    if (
        url.scheme != "https"
        or url.netloc != "download.docker.com"
        or not url.path.startswith("/linux/ubuntu/")
        or url.query
        or url.fragment
    ):
        message = "invalid declared Docker package URL"
        raise ValueError(message)
    if not re.fullmatch(r"[a-z][a-z0-9.-]*", record["package"]):
        message = "invalid declared Docker package name"
        raise ValueError(message)
    with urllib.request.urlopen(record["url"], timeout=120) as response:  # noqa: S310 - fixed HTTPS Docker host validated above
        body = response.read(record["bytes"] + 1)
    if (
        len(body) != record["bytes"]
        or hashlib.sha256(body).hexdigest() != record["sha256"]
    ):
        message = "Docker package artifact differs from declared lock"
        raise ValueError(message)
    path = directory / (record["package"] + ".deb")
    path.write_bytes(body)
    for field, key in [
        ("Package", "package"),
        ("Version", "version"),
        ("Architecture", "architecture"),
    ]:
        actual = subprocess.check_output(  # noqa: S603 - fixed native package query with declared identities
            ["/usr/bin/dpkg-deb", "-f", str(path), field], text=True
        ).strip()
        if actual != record[key]:
            message = "Docker package identity differs from declared lock"
            raise ValueError(message)
    return path


def verify_installed(records: list[dict]) -> None:
    """Require exact installed package identities after the declared installation."""
    for record in records:
        actual = subprocess.check_output(  # noqa: S603 - fixed native package query with declared identities
            [
                "/usr/bin/dpkg-query",
                "-W",
                "-f=${Version}\t${Architecture}",
                record["package"],
            ],
            text=True,
        ).strip()
        if actual != record["version"] + "\t" + record["architecture"]:
            message = "installed Docker package differs from declared lock"
            raise ValueError(message)


def install(lock: Path = LOCK) -> None:
    """Download all artifacts before installation; temporary files are always removed."""
    records = locked_records(lock)
    with tempfile.TemporaryDirectory(prefix="origin-docker-packages-") as temporary:
        paths = [download_package(record, Path(temporary)) for record in records]
        subprocess.run(  # noqa: S603 - fixed apt invocation with verified local archives
            [
                "/usr/bin/apt-get",
                "install",
                "-y",
                "-o",
                "DPkg::Lock::Timeout=60",
                *map(str, paths),
            ],
            check=True,
        )
    verify_installed(records)


if __name__ == "__main__":
    install()
