"""Per-run DVWA recovery preserves unrelated guestbook rows and uploads."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from catalog_dvwa_recovery import expected_uploads, validate_inventory
from catalog_family_recovery import operate


def test_dvwa_inventory_accepts_exact_payload_hashes_and_rejects_ambiguity():
    marker = "tgen-" + "a" * 32
    uploads = expected_uploads(marker)
    filename, digest = next(iter(uploads.items()))
    inventory: dict = {
        "uploads": {filename: digest},
        "guestbook": [
            {"comment_id": 2, "name": "test", "comment": marker + " payload"}
        ],
    }
    validate_inventory(inventory, marker)
    inventory["uploads"][filename] = "f" * 64
    with pytest.raises(ValueError, match="changed"):
        validate_inventory(inventory, marker)
    inventory["uploads"] = {marker + "-foreign.php": digest}
    with pytest.raises(ValueError, match="unowned"):
        validate_inventory(inventory, marker)
    inventory["uploads"] = {}
    inventory["guestbook"][0]["comment"] = "foreign"
    with pytest.raises(ValueError, match="unowned"):
        validate_inventory(inventory, marker)


def test_dvwa_journal_uses_unique_marker_and_requires_empty_owned_namespace(tmp_path):
    request = {"action": "snapshot", "family": "dvwa", "identity": "a" * 32}
    empty: dict = {"uploads": {}, "guestbook": []}
    with patch("catalog_family_recovery.dvwa_database", return_value=empty) as database:
        before = operate(request, tmp_path)
        assert before["marker"] == "tgen-" + "a" * 32
        assert set(before["replicas"]) == {"dvwa-" + str(i) for i in range(1, 5)}
        after = operate({**request, "action": "restore"}, tmp_path)
        assert after["after"] == before["replicas"]
        assert database.call_count == 8
        assert (
            json.loads((tmp_path / ("dvwa-" + "a" * 32 + ".json")).read_text())[
                "family"
            ]
            == "dvwa"
        )
