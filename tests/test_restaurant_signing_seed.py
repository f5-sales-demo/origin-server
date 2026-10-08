"""Pinned synthetic signing configuration is deterministic and rejects upstream drift."""

import json
from pathlib import Path

import pytest


def test_signing_adapter_is_repeatable_and_rejects_changed_upstream(tmp_path):
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / "provisioning/files.json").read_text())
    source = next(
        r["content"]
        for r in rows
        if r["path"] == "/opt/origin-server/adapt-restaurant.py"
    )
    source = source[source.index("config = root / 'app/config.py'") :]
    (tmp_path / "app").mkdir()
    file = tmp_path / "app/config.py"
    file.write_text("JWT_SECRET_KEY: str = generate_random_secret()\n")
    for _ in range(2):
        exec(compile(source, "signing-adapter", "exec"), {"root": tmp_path})  # noqa: S102 - exact declared adapter fixture  # pylint: disable=exec-used
    assert file.read_text() == 'JWT_SECRET_KEY: str = "97953"\n'
    file.write_text("upstream changed")
    with pytest.raises(ValueError, match="signing configuration changed"):
        exec(compile(source, "signing-adapter", "exec"), {"root": tmp_path})  # noqa: S102 - exact declared adapter fixture  # pylint: disable=exec-used
