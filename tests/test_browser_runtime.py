"""Interrupted browser verification must retain failure and remove only its owned container."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from browser_runtime import cleanup_container, evidence_directory, main, retain_evidence


def test_foreign_browser_container_is_preserved():
    with patch("browser_runtime.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(
            {
                "Name": "/origin-browser-owned",
                "Config": {"Labels": {"org.f5.demo.verifier": "foreign"}},
            }
        )
        with pytest.raises(ValueError, match="ownership"):
            cleanup_container("origin-browser-owned", "owned")
        assert run.call_count == 1


def test_owned_browser_container_cleanup_uses_exact_identity():
    with patch("browser_runtime.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(
            {
                "Name": "/origin-browser-owned",
                "Config": {"Labels": {"org.f5.demo.verifier": "owned"}},
            }
        )
        cleanup_container("origin-browser-owned", "owned")
        assert run.call_args.args[0] == [
            "/usr/bin/docker",
            "rm",
            "--force",
            "origin-browser-owned",
        ]


def test_evidence_directory_rejects_symlink_before_resolution(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        evidence_directory(link)


def test_browser_retention_preserves_active_and_unrelated_directories(tmp_path):
    active = tmp_path / "private-browser-active"
    old = tmp_path / "private-browser-old"
    foreign = tmp_path / "unrelated"
    for directory in (active, old, foreign):
        directory.mkdir()
        (directory / "evidence.png").write_bytes(b"x" * 100)
    (old / "runtime-receipt.json").write_text('{"cleanup":true}')
    os.utime(old, (1, 1))
    retain_evidence(tmp_path, active, days=7, max_bytes=1000)
    assert active.exists()
    assert foreign.exists()
    assert not old.exists()


def test_browser_retention_refuses_unowned_directory_eviction(tmp_path):
    active = tmp_path / "private-browser-active"
    active.mkdir()
    foreign = tmp_path / "private-browser-foreign"
    foreign.mkdir()
    (foreign / "evidence.png").write_bytes(b"x" * 200)
    os.utime(foreign, (1, 1))
    retain_evidence(tmp_path, active, days=7, max_bytes=1)
    assert foreign.exists()


def test_signup_browser_kind_is_accepted_before_required_argument_check(capsys):
    with (
        patch("sys.argv", ["origin-browser-verify", "crapi-signup"]),
        pytest.raises(SystemExit),
    ):
        main()
    assert "invalid choice" not in capsys.readouterr().err
