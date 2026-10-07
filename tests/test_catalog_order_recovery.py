"""Order recovery rejects caller-supplied baselines and changed journal identity."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from catalog_order_recovery import operation
from enroll_signup_recovery import enroll


def baseline():
    return {
        "email": "tgen-order@example.com",
        "order": {
            "id": 1,
            "user_id": 5,
            "product_id": 1,
            "transaction_id": "synthetic",
            "created_on": "2026-01-01",
            "quantity": 1,
            "status": "delivered",
        },
        "credit": 100,
    }


def test_baseline_is_host_journaled_and_repeat_restore_is_exact(tmp_path):
    value = {"action": "snapshot", "identity": "a" * 32, "order": 1}
    before = baseline()
    with (
        patch("catalog_order_recovery.owner"),
        patch("catalog_order_recovery.snapshot", return_value=before),
        patch("catalog_order_recovery.restore", return_value=before) as restore,
    ):
        saved = operation(value, tmp_path)
        assert saved["before"] == before
        assert (tmp_path / ("a" * 32 + ".json")).stat().st_mode & 0o077 == 0
        result = operation({**value, "action": "restore"}, tmp_path)
        assert result["restored"]
        operation({**value, "action": "restore"}, tmp_path)
        assert restore.call_count == 2


def test_extra_fields_foreign_identity_and_symlink_never_write(tmp_path):
    value = {"action": "snapshot", "identity": "a" * 32, "order": 1}
    with pytest.raises(ValueError, match="invalid synthetic"):
        operation({**value, "before": baseline()}, tmp_path)
    with pytest.raises(ValueError, match="invalid synthetic"):
        operation({**value, "identity": "../foreign"}, tmp_path)
    (tmp_path / ("a" * 32 + ".json")).symlink_to(tmp_path / "foreign")
    with pytest.raises(ValueError, match="unsafe order journal"):
        operation(value, tmp_path)


def test_changed_order_or_actor_baseline_is_rejected(tmp_path):
    value = {"action": "restore", "identity": "a" * 32, "order": 1}
    (tmp_path / ("a" * 32 + ".json")).write_text(
        json.dumps({"identity": "a" * 32, "order": 2, "before": baseline()})
    )
    with (
        patch("catalog_order_recovery.owner"),
        pytest.raises(ValueError, match="ownership changed"),
    ):
        operation(value, tmp_path)


def test_order_enrollment_keeps_signup_and_foreign_keys(tmp_path):
    public = "ssh-ed25519 " + "A" * 68
    enroll(public, tmp_path)
    enroll(public, tmp_path, "order")
    rows = (tmp_path / "authorized_keys").read_text().splitlines()
    assert len(rows) == 2
    assert any('command="/usr/local/bin/catalog-order-recovery"' in row for row in rows)
    assert any(
        'command="/usr/local/bin/catalog-signup-recovery"' in row for row in rows
    )


def test_second_journal_requires_prior_recovery(tmp_path):
    value = {"action": "snapshot", "identity": "a" * 32, "order": 1}
    with (
        patch("catalog_order_recovery.owner"),
        patch("catalog_order_recovery.snapshot", return_value=baseline()),
        patch("catalog_order_recovery.restore", return_value=baseline()),
    ):
        operation(value, tmp_path)
        with pytest.raises(ValueError, match="requires recovery"):
            operation({**value, "identity": "b" * 32}, tmp_path)
        operation({**value, "action": "restore"}, tmp_path)
        operation({**value, "identity": "b" * 32}, tmp_path)
        with pytest.raises(ValueError, match="another active"):
            operation({**value, "action": "restore"}, tmp_path)
