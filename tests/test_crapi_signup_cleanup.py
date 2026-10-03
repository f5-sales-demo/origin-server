"""Signup cleanup must reject foreign fixtures before touching database or MailHog."""

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from crapi_signup_cleanup import recover_signup


def test_foreign_signup_identity_cannot_authorize_cleanup(tmp_path):
    (tmp_path / "fixture-journal.json").write_text(
        json.dumps({"email": "other@example.com", "number": "5550000000"})
    )
    with patch("crapi_signup_cleanup.subprocess.run") as database:
        with pytest.raises(ValueError, match="identity"):
            recover_signup(tmp_path)
        database.assert_not_called()


def test_signup_database_uses_quoted_psql_variables(tmp_path):
    fixture: dict[str, Any] = {
        "email": "signup-" + "a" * 32 + "@example.com",
        "number": "5550000000",
        "vehicle_vin": "TESTV123456789012",
        "mail_ids": [],
    }
    (tmp_path / "fixture-journal.json").write_text(json.dumps(fixture))
    with patch("crapi_signup_cleanup.subprocess.run") as database:
        database.return_value.stdout = "1\n0\n"
        result = recover_signup(tmp_path)
        assert not result["passed"]
        sql = database.call_args.kwargs["input"]
        assert fixture["email"] not in sql
        assert ":'email'" in sql
        assert "email=" + fixture["email"] in database.call_args.args[0]
