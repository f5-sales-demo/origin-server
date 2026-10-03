"""Interrupted browser verification must retain failure and remove only its owned container."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from browser_runtime import cleanup_container, evidence_directory


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
