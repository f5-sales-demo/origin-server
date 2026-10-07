#!/usr/bin/env python3
"""Enroll a single forced-command public key for exact synthetic signup recovery."""

import os
import re
import sys
from pathlib import Path

KEY_LIMIT = 256
MARKER = "waap-catalog-signup-recovery"


def enroll(public: str, directory: Path, kind: str = "signup") -> None:
    """Preserve other root SSH keys and constrain this dedicated key to one helper."""
    if kind not in ("signup", "order"):
        message = "unknown synthetic recovery kind"
        raise ValueError(message)
    marker = MARKER if kind == "signup" else "waap-catalog-order-recovery"
    helper = "/usr/local/bin/catalog-" + kind + "-recovery"
    if len(public) > KEY_LIMIT or not re.fullmatch(
        r"ssh-ed25519 [A-Za-z0-9+/=]{60,120}(?: [A-Za-z0-9-]+)?", public
    ):
        message = "dedicated Ed25519 public key required"
        raise ValueError(message)
    if directory.is_symlink():
        message = "SSH directory cannot be a symlink"
        raise ValueError(message)
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / "authorized_keys"
    if path.is_symlink():
        message = "SSH keys cannot be a symlink"
        raise ValueError(message)
    rows = path.read_text().splitlines() if path.exists() else []
    rows = [row for row in rows if not row.endswith(" " + marker)]
    key = " ".join(public.split()[:2])
    rows.append('restrict,command="' + helper + '" ' + key + " " + marker)
    temporary = directory / "authorized_keys.catalog.tmp"
    with temporary.open("x") as stream:
        stream.write("\n".join(rows) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


if __name__ == "__main__":
    os.umask(0o077)
    enroll(
        sys.stdin.read(KEY_LIMIT + 1).strip(),
        Path("/root/.ssh"),
        "order" if Path(sys.argv[0]).name == "enroll-order-recovery" else "signup",
    )
