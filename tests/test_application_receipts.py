"""Partial or foreign browser evidence cannot satisfy application completeness."""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from application_receipts import browser_assertions, coverage_matrix


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
    receipt = {
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
