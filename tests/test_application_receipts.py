"""Partial or foreign browser evidence cannot satisfy application completeness."""

import copy
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from application_receipts import browser_assertions, coverage_matrix, csd_replica_state


def test_browser_assertions_reject_foreign_sources_layers_and_partial_checks():
    provenance = {"source_commit": "a" * 40, "archive_sha256": "b" * 64}
    runtime = {
        **provenance,
        "base": "http://example.test",
        "kind": "dvwa",
        "verifier_sha256": "d" * 64,
        "exit_code": 0,
        "cleanup": True,
    }
    receipt: dict[str, Any] = {
        "passed": True,
        "browser_closed": True,
        "errors": [],
        "checks": [
            {"name": name, "passed": True}
            for name in [
                "authenticated-home",
                "security-form",
                "seeded-sql-page",
                "reflected-form",
            ]
        ],
    }
    assert "styles-and-forms" in browser_assertions(
        "dvwa", receipt, runtime, provenance, "http://example.test"
    )
    for key, value in [
        ("source_commit", "c" * 40),
        ("archive_sha256", "c" * 64),
        ("base", "http://other.test"),
        ("exit_code", 1),
        ("cleanup", False),
    ]:
        assert not browser_assertions(
            "dvwa", receipt, {**runtime, key: value}, provenance, "http://example.test"
        )
    failed = copy.deepcopy(receipt)
    failed["checks"][0]["passed"] = False
    assert not browser_assertions(
        "dvwa", failed, runtime, provenance, "http://example.test"
    )


def test_matrix_requires_each_replica_and_published_layer():
    manifest = {
        "applications": [{"id": "dvwa", "ports": [8101, 8102], "workflows": ["login"]}]
    }
    observations = [
        {"application": "dvwa", "layer": layer, "assertions": ["login"]}
        for layer in [
            "origin-nginx",
            "http-www",
            "http-api",
            "https-www",
            "https-api",
            "native-8101",
        ]
    ]
    assert not coverage_matrix(manifest, observations)["complete"]
    observations.append(
        {"application": "dvwa", "layer": "native-8102", "assertions": ["login"]}
    )
    assert coverage_matrix(manifest, observations)["complete"]


def test_csd_replica_state_requires_visibility_and_restores_tagged_entry():
    entries = [{"fixture_id": "unrelated", "payload": {"demo_id": "retained"}}]

    class Response:
        status = 200

        def __init__(self, document):
            self.document = document

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.document).encode()

    def open_request(request, timeout):
        marker = request.headers["X-demo-fixture"]
        if request.full_url.endswith("/exfil"):
            entries.append({"fixture_id": marker, "payload": json.loads(request.data)})
            return Response({"status": "received"})
        if request.full_url.endswith("/exfil/clear"):
            entries[:] = [entry for entry in entries if entry["fixture_id"] != marker]
            return Response({"status": "cleared"})
        return Response(list(entries))

    with patch("application_receipts.urlopen", side_effect=open_request):
        observations = csd_replica_state([("origin-nginx", "http://example.test")])
    assert len(observations) == 5
    assert entries == [{"fixture_id": "unrelated", "payload": {"demo_id": "retained"}}]


def test_signup_browser_assertions_require_verified_fixture_recovery():
    provenance = {"source_commit": "a" * 40, "archive_sha256": "b" * 64}
    runtime = {
        **provenance,
        "base": "http://example.test",
        "kind": "crapi-signup",
        "exit_code": 0,
        "cleanup": True,
        "verifier_sha256": "d" * 64,
    }
    receipt = {
        "passed": True,
        "browser_closed": True,
        "errors": [],
        "checks": [
            {"name": name, "passed": True}
            for name in ["signup-submit", "signup-mailhog", "mailhog-render"]
        ],
    }
    assert not browser_assertions(
        "crapi-signup", receipt, runtime, provenance, "http://example.test"
    )
    runtime["fixture_recovery"] = {"passed": True}
    assert browser_assertions(
        "crapi-signup", receipt, runtime, provenance, "http://example.test"
    ) == {"signup", "mailhog"}
