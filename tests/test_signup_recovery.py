"""Exact signup recovery enrollment rejects arbitrary commands and foreign identities."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from catalog_signup_recovery import recover
from enroll_signup_recovery import enroll


def test_enrollment_preserves_existing_keys_and_restricts_new_key(tmp_path):
    folder = tmp_path / "ssh"
    folder.mkdir()
    (folder / "authorized_keys").write_text("preserved-key\n")
    enroll("ssh-ed25519 " + "A" * 68, folder)
    rows = (folder / "authorized_keys").read_text()
    assert rows.startswith("preserved-key\n")
    assert 'restrict,command="/usr/local/bin/catalog-signup-recovery"' in rows
    enroll("ssh-ed25519 " + "B" * 68, folder)
    assert (folder / "authorized_keys").read_text().count(
        "waap-catalog-signup-recovery"
    ) == 1
    with pytest.raises(ValueError, match="Ed25519"):
        enroll("ssh-ed25519 malicious\ncommand", folder)


def test_recovery_rejects_unknown_fields_before_native_cleanup(tmp_path):
    with patch("catalog_signup_recovery.recover_signup") as cleanup:
        with pytest.raises(ValueError, match="journal"):
            recover({"command": "delete-all"}, tmp_path)
        cleanup.assert_not_called()
