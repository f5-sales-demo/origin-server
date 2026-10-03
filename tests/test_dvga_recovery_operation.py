"""Functional recovery probes use the same accepted operation as native readiness."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_recovery_probe_matches_accepted_seeded_paste_operation():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    source = next(
        item["content"]
        for item in files
        if item["path"] == "/usr/local/bin/demo-dvga-recovery"
    )
    assert "query getPastes" in source
    assert "limit: 1" in source


def test_recovery_checks_running_container_provenance_and_compose_owner():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    source = next(
        item["content"]
        for item in files
        if item["path"] == "/usr/local/bin/demo-dvga-recovery"
    )
    assert 'container["Config"]' in source
    assert "com.docker.compose.project" in source
    assert "origin-server" in source
