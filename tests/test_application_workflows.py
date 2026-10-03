"""Authentication and fixture content cannot be replaced by successful HTTP codes."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    """Load the reusable application workflow verifier."""
    spec = importlib.util.spec_from_file_location(
        "verify_workflows", ROOT / "scripts/verify_workflows.py"
    )
    assert spec is not None
    assert spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_issued_token_must_exist_in_correct_response_shape():
    """A landing document or empty token fails authentication evidence."""
    verifier = module()
    with pytest.raises(ValueError, match="issued token"):
        verifier.issued_token({"status": "healthy"}, "auth_token")
    with pytest.raises(ValueError, match="issued token"):
        verifier.issued_token({"auth_token": ""}, "auth_token")
    assert (
        verifier.issued_token({"auth_token": "synthetic-issued-token"}, "auth_token")
        == "synthetic-issued-token"
    )


def test_workflow_report_requires_every_declared_app():
    """Missing workflow results cannot produce a complete report."""
    verifier = module()
    assert not verifier.complete_report(
        {"checks": [{"application": "dvwa", "passed": True}]}, {"dvwa", "crapi"}
    )
    assert not verifier.complete_report(
        {"checks": [{"application": "dvwa", "passed": False}]}, {"dvwa"}
    )
    assert verifier.complete_report(
        {"checks": [{"application": "dvwa", "passed": True}]}, {"dvwa"}
    )


def test_mailhog_json_response_is_application_content():
    """MailHog's declared text/json MIME type must be explicit at its route."""
    verifier = module()
    assert verifier.json_content_type("text/json", {"application/json", "text/json"})
    assert not verifier.json_content_type(
        "text/html", {"application/json", "text/json"}
    )
    assert not verifier.json_content_type("text/json", {"application/json"})


def test_export_includes_real_vampi_authentication():
    """Publicly blocked setup must not leave the origin-issued API fixture absent."""
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    source = next(
        item["content"]
        for item in files
        if item["path"] == "/usr/local/bin/demo-catalog-fixtures"
    )
    assert 'result["vampi_token"]' in source
    assert "http://127.0.0.1:5101/users/v1/login" in source
