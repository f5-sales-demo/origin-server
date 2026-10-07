#!/usr/bin/env python3
"""Recover only an exact synthetic signup journal through a forced SSH command."""

import json
import os
import sys
import tempfile
from pathlib import Path

from crapi_signup_cleanup import recover_signup

MAX_INPUT_BYTES = 16384


def recover(value: dict, directory: Path) -> dict:
    """Delegate identity and vehicle ownership checks to the existing recovery code."""
    if not isinstance(value, dict) or set(value) - {
        "email",
        "number",
        "vehicle_vin",
        "mail_ids",
        "vehicle_registered",
        "submitted",
    }:
        message = "invalid synthetic signup recovery journal"
        raise ValueError(message)
    (directory / "fixture-journal.json").write_text(json.dumps(value))
    (directory / "fixture-journal.json").chmod(0o600)
    return recover_signup(directory)


def main() -> int:
    """Accept bounded JSON only; no remote arguments or shell interpretation."""
    os.umask(0o077)
    if os.environ.get("SSH_ORIGINAL_COMMAND", "") not in ("", "recover-signup"):
        return 2
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        return 2
    try:
        value = json.loads(raw)
        with tempfile.TemporaryDirectory(
            prefix="catalog-signup-", dir="/opt/origin-server"
        ) as temporary:
            print(json.dumps(recover(value, Path(temporary))))
    except (OSError, ValueError, KeyError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
