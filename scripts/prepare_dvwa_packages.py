#!/usr/bin/env python3
"""Prepare exact verified Debian packages for the offline DVWA container build."""

import hashlib
import json
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

LOCK = Path("/opt/origin-server/dvwa-build-packages.json")
DESTINATION = Path("/opt/origin-server/dvwa-fpm/packages")
BASE_IMAGE = (
    "php@sha256:584e584083bada479f0ee733a3025722a68e366eb721e618d1b6a252e4ff45c5"
)


EXPECTED_PACKAGES = {
    "nginx-common",
    "libjpeg62-turbo-dev",
    "libjpeg62-turbo",
    "libfreetype-dev",
    "libelf1t64",
    "libfreetype6",
    "libpng16-16t64",
    "libtirpc-common",
    "libbrotli-dev",
    "iputils-ping",
    "libtirpc3t64",
    "libbpf1",
    "libmnl0",
    "zlib1g-dev",
    "libxtables12",
    "libbz2-dev",
    "nginx",
    "libcap2-bin",
    "libpng-dev",
    "iproute2",
}


def locked_records(lock: Path) -> list[dict]:
    """Reject malformed or incomplete package ownership before downloads or commands."""
    value = json.loads(lock.read_text())
    records = value.get("packages", [])
    if (
        value.get("schema_version") != 1
        or value.get("snapshot") != "20261012T000000Z"
        or value.get("base_image") != BASE_IMAGE
        or not isinstance(records, list)
        or len(records) != len(EXPECTED_PACKAGES)
    ):
        message = "invalid DVWA package lock"
        raise ValueError(message)
    names = set()
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get("package") not in EXPECTED_PACKAGES
        ):
            message = "invalid DVWA package lock identity"
            raise ValueError(message)
        validate_url(record["url"])
        names.add(record["package"])
        size = record.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            message = "invalid DVWA package lock artifact size"
            raise ValueError(message)
        if (
            record.get("architecture") not in ("amd64", "all")
            or not isinstance(record.get("version"), str)
            or not record["version"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))
        ):
            message = "invalid DVWA package lock artifact"
            raise ValueError(message)
    if names != EXPECTED_PACKAGES:
        message = "incomplete DVWA package lock"
        raise ValueError(message)
    return records


def validate_url(value: str) -> None:
    """Reject any download outside the exact declared Debian snapshot."""
    url = urllib.parse.urlsplit(value)
    if (
        url.scheme != "https"
        or url.netloc != "snapshot.debian.org"
        or not url.path.startswith(
            (
                "/archive/debian/20261012T000000Z/pool/",
                "/archive/debian-security/20261012T000000Z/pool/",
            )
        )
        or bool(url.query or url.fragment)
        or ".." in urllib.parse.unquote(url.path).split("/")
    ):
        message = "invalid declared Debian package lock URL"
        raise ValueError(message)


def download(record: dict, directory: Path) -> Path:
    """Verify immutable bytes and all native identities before staging a package."""
    validate_url(record["url"])
    if not re.fullmatch(r"[a-z][a-z0-9.-]*", record["package"]):
        message = "invalid declared DVWA package name"
        raise ValueError(message)
    # The HTTPS snapshot host and path are validated above.
    with urllib.request.urlopen(record["url"], timeout=120) as response:  # noqa: S310
        body = response.read(record["size"] + 1)
    if (
        len(body) != record["size"]
        or hashlib.sha256(body).hexdigest() != record["sha256"]
    ):
        message = "DVWA package artifact differs from declared lock"
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
            message = "DVWA package identity differs from declared lock"
            raise ValueError(message)
    return path


def prepare(lock: Path = LOCK, destination: Path = DESTINATION) -> None:
    """Publish a complete verified package set only after every download passes."""
    records = locked_records(lock)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".dvwa-packages-", dir=destination.parent
    ) as temporary:
        staging = Path(temporary)
        paths = [download(record, staging) for record in records]
        checksums = "".join(
            record["sha256"] + "  " + path.name + "\n"
            for record, path in zip(records, paths, strict=True)
        )
        (staging / "SHA256SUMS").write_text(checksums)
        destination.mkdir(exist_ok=True)
        for existing in destination.iterdir():
            if existing.name not in {path.name for path in paths} | {"SHA256SUMS"}:
                message = "unknown file in owned DVWA package directory"
                raise ValueError(message)
        for path in [*paths, staging / "SHA256SUMS"]:
            path.replace(destination / path.name)


if __name__ == "__main__":
    prepare()
