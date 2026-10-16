"""Initialize native DVGA seeds once and preserve existing SQLite fixtures."""

import sqlite3
import stat
import subprocess
import sys
from pathlib import Path


def verify_database(database: Path) -> None:
    """Reject invalid existing fixtures without destructive native reseeding."""
    if not stat.S_ISREG(database.lstat().st_mode):
        message = "Native DVGA database must be a regular file"
        raise ValueError(message)
    with sqlite3.connect(
        database.resolve().as_uri() + "?mode=ro", uri=True
    ) as connection:
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            message = "Native DVGA database integrity check failed"
            raise ValueError(message)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"users", "pastes", "audits"}.issubset(tables):
            message = "Native DVGA database schema is incomplete"
            raise ValueError(message)


def initialize_database(database: Path, setup: Path) -> bool:
    """Run unchanged native setup only for an absent database; propagate failures."""
    database = Path(database)
    setup = Path(setup)
    try:
        database.lstat()
    except FileNotFoundError:
        subprocess.run(  # noqa: S603 - exact declared native initializer
            [sys.executable, str(setup.resolve())], cwd=setup.parent, check=True
        )
        if not database.exists():
            message = "Native DVGA initializer did not create its database"
            raise ValueError(message) from None
        verify_database(database)
        return True
    verify_database(database)
    return False
