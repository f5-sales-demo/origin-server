"""crAPI family restores only the dedicated actor's captured rows and credit."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from catalog_crapi_recovery import crapi_database


def test_crapi_family_requires_dedicated_actor_and_exact_readback():
    before = {
        "email": "tgen-order@example.com",
        "user": 7,
        "credit": 100,
        "orders": [],
        "coupons": [],
    }
    with (
        patch("catalog_crapi_recovery.owner"),
        patch("catalog_crapi_recovery.sql", return_value=before) as sql,
    ):
        assert crapi_database("crapi", "snapshot", "tgen-" + "a" * 32) == before
        assert crapi_database("crapi", "restore", "tgen-" + "a" * 32, before) == before
        assert 'DELETE FROM "order"' in sql.call_args.args[0]
        assert "user_id" in sql.call_args.args[0]
    with (
        patch("catalog_crapi_recovery.owner"),
        patch(
            "catalog_crapi_recovery.sql",
            return_value={**before, "email": "foreign@example.com"},
        ),
        pytest.raises(ValueError, match="actor"),
    ):
        crapi_database("crapi", "snapshot", "tgen-" + "a" * 32)
