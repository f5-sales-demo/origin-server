"""Package corruption and native identity drift must fail before acceptance."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "docker_packages", ROOT / "scripts/install_docker_packages.py"
)
assert spec
assert spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def record(body):
    return {
        "package": "docker-ce",
        "version": "5:29.8.1-1~ubuntu.24.04~noble",
        "architecture": "amd64",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "url": "https://download.docker.com/linux/ubuntu/package.deb",
    }


def test_corrupt_package_never_reaches_package_identity_check(tmp_path):
    with (
        patch.object(module.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")),
        patch.object(module.subprocess, "check_output") as command,
    ):
        with pytest.raises(ValueError, match="artifact differs"):
            module.download_package(record(b"good"), tmp_path)
        command.assert_not_called()
        assert not list(tmp_path.iterdir())


def test_exact_artifact_requires_all_native_identity_fields(tmp_path):
    item = record(b"good")
    with (
        patch.object(
            module.urllib.request, "urlopen", return_value=io.BytesIO(b"good")
        ),
        patch.object(
            module.subprocess,
            "check_output",
            side_effect=["docker-ce", item["version"], "amd64"],
        ),
    ):
        assert module.download_package(item, tmp_path).read_bytes() == b"good"
    with (
        patch.object(
            module.urllib.request, "urlopen", return_value=io.BytesIO(b"good")
        ),
        patch.object(module.subprocess, "check_output", return_value="unrelated"),
        pytest.raises(ValueError, match="identity differs"),
    ):
        module.download_package(item, tmp_path)


def test_installed_package_version_and_architecture_must_match():
    item = record(b"good")
    with patch.object(
        module.subprocess, "check_output", return_value=item["version"] + "\tamd64"
    ):
        module.verify_installed([item])
    for actual in ("old\tamd64", item["version"] + "\tarm64"):
        with (
            patch.object(module.subprocess, "check_output", return_value=actual),
            pytest.raises(ValueError, match="installed Docker package"),
        ):
            module.verify_installed([item])


def test_all_packages_verify_before_install_and_temporary_files_are_removed(tmp_path):
    lock = tmp_path / "lock.json"
    lock.write_text("unused synthetic lock")
    observed = []

    def download(item, directory):
        observed.append(directory)
        path = directory / (str(len(observed)) + ".deb")
        path.write_bytes(b"verified")
        return path

    with (
        patch.object(
            module, "locked_records", return_value=[record(b"one"), record(b"two")]
        ),
        patch.object(module, "download_package", side_effect=download),
        patch.object(module.subprocess, "run") as command,
        patch.object(module, "verify_installed") as readback,
    ):
        module.install(lock)
        command.assert_called_once()
        assert len(command.call_args.args[0]) == 7
        readback.assert_called_once()
    assert not observed[0].exists()

    with (
        patch.object(module, "locked_records", return_value=[record(b"one")]),
        patch.object(module, "download_package", side_effect=ValueError("corrupt")),
        patch.object(module.subprocess, "run") as command,
        pytest.raises(ValueError, match="corrupt"),
    ):
        module.install(lock)
    command.assert_not_called()


def test_lock_rejects_missing_duplicate_and_malformed_artifacts(tmp_path):
    lock = tmp_path / "lock.json"
    rows = [
        {**record(b"good"), "package": name}
        for name in sorted(module.EXPECTED_PACKAGES)
    ]
    lock.write_text(json.dumps({"schema_version": 1, "packages": rows}))
    assert module.locked_records(lock) == rows
    for invalid in (
        rows[:-1],
        [rows[0]] * 5,
        [{**rows[0], "sha256": "wrong"}, *rows[1:]],
        [{**rows[0], "bytes": True}, *rows[1:]],
    ):
        lock.write_text(json.dumps({"schema_version": 1, "packages": invalid}))
        with pytest.raises(ValueError, match="package lock"):
            module.locked_records(lock)
