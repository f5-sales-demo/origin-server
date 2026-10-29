"""DVWA builds must consume exact verified offline package artifacts."""

import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import prepare_dvwa_packages as module
import pytest

ROOT = Path(__file__).resolve().parents[1]


def record(body):
    """Return an exact synthetic Debian artifact declaration."""
    return {
        "package": "nginx",
        "version": "1.0",
        "architecture": "amd64",
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "url": (
            "https://snapshot.debian.org/archive/debian/20261012T000000Z/"
            "pool/main/n/nginx/nginx.deb"
        ),
    }


def test_corruption_and_identity_mismatch_reject_before_build(tmp_path):
    """Require byte integrity before native identity or Docker can run."""
    with (
        patch.object(module.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")),
        patch.object(module.subprocess, "check_output") as command,
    ):
        with pytest.raises(ValueError, match="artifact differs"):
            module.download(record(b"good"), tmp_path)
        command.assert_not_called()
    with (
        patch.object(
            module.urllib.request, "urlopen", return_value=io.BytesIO(b"good")
        ),
        patch.object(module.subprocess, "check_output", return_value="wrong"),
        pytest.raises(ValueError, match="identity differs"),
    ):
        module.download(record(b"good"), tmp_path)


def test_complete_lock_is_bound_to_exact_base_and_dependencies(tmp_path):
    """Reject missing, duplicate, mutable or malformed package declarations."""
    value = json.loads((ROOT / "provisioning/dvwa-build-packages.json").read_text())
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(value))
    assert len(module.locked_records(lock)) == 20
    for records in (
        value["packages"][:-1],
        [value["packages"][0]] * 20,
        [{**value["packages"][0], "sha256": "bad"}, *value["packages"][1:]],
        [
            {**value["packages"][0], "url": "https://deb.debian.org/package.deb"},
            *value["packages"][1:],
        ],
    ):
        lock.write_text(json.dumps({**value, "packages": records}))
        with pytest.raises(ValueError, match="lock"):
            module.locked_records(lock)


def test_dvwa_build_has_no_network_package_resolution():
    """Retain all PHP extensions while installing only declared local packages."""
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    by_path = {item["path"]: item["content"] for item in files}
    dockerfile = by_path["/opt/origin-server/dvwa-fpm/Dockerfile"]
    assert "apt-get" not in dockerfile
    assert "COPY packages/ /tmp/packages/" in dockerfile
    assert "sha256sum -c SHA256SUMS" in dockerfile
    assert "dpkg -i /tmp/packages/*.deb" in dockerfile
    assert "docker-php-ext-install mysqli pdo pdo_mysql gd" in dockerfile
    provision = by_path["/usr/local/bin/demo-origin-provision"]
    assert provision.index("origin-prepare-dvwa-packages") < provision.index(
        "docker compose build"
    )


def test_failed_preparation_preserves_existing_complete_set(tmp_path):
    """A failed download must preserve the previously declared build inputs."""
    destination = tmp_path / "packages"
    destination.mkdir()
    existing = destination / "nginx.deb"
    existing.write_bytes(b"previous")
    with (
        patch.object(module, "locked_records", return_value=[record(b"new")]),
        patch.object(module, "download", side_effect=ValueError("corrupt")),
        pytest.raises(ValueError, match="corrupt"),
    ):
        module.prepare(tmp_path / "lock.json", destination)
    assert existing.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [destination]
