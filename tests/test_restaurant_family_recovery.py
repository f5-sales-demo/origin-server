"""RESTaurant recovery is scoped to declared rows and unique actor markers."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from catalog_restaurant_recovery import restore_sql, validate_snapshot


def baseline():
    return {
        "users": [
            {"id": 1, "username": "chef", "password": "synthetic", "role": "CHEF"}
        ],
        "menu": [{"id": 1, "name": "Pollos Classic Breakfast"}],
        "temporary_users": [],
    }


def test_restaurant_baseline_requires_declared_identity_and_empty_run_namespace():
    value = baseline()
    validate_snapshot(value)
    value["temporary_users"] = [{"id": 2, "username": "foreign"}]
    with pytest.raises(ValueError, match="namespace"):
        validate_snapshot(value)
    value = baseline()
    value["users"][0]["username"] = "foreign"
    with pytest.raises(ValueError, match="identity"):
        validate_snapshot(value)


def test_restaurant_restore_sql_has_transaction_and_ownership_guards():
    sql = restore_sql(baseline(), "tgen-" + "a" * 32)
    assert "BEGIN" in sql
    assert "COMMIT" in sql
    assert "unrelated orders" in sql
    assert "unrelated coupons" in sql
    assert "actor identity changed" in sql
    assert "menu identity changed" in sql
    assert "DELETE FROM users WHERE username = ANY" in sql
    assert "DELETE FROM menu_items" not in sql
    with pytest.raises(ValueError, match="marker"):
        restore_sql(baseline(), "x'; DELETE FROM users;")
