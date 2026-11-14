"""Scoped family journals reject arbitrary rows and recover all declared replicas."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from catalog_family_recovery import SQLITE_HELPER, VAMPI_ACTORS, operate


def test_family_journal_restores_four_replica_baselines(tmp_path):
    baseline = {"users": [{"id": 1, "username": "admin"}], "books": []}
    request = {"action": "snapshot", "family": "vampi", "identity": "a" * 32}
    with patch("catalog_family_recovery.database", return_value=baseline) as database:
        saved = operate(request, tmp_path)
        assert len(saved["replicas"]) == 4
        result = operate({**request, "action": "restore"}, tmp_path)
        assert result["restored"]
        assert result["after"] == saved["replicas"]
        assert database.call_count == 8
        assert (tmp_path / ("vampi-" + "a" * 32 + ".json")).stat().st_mode & 0o077 == 0


def test_unknown_family_extra_data_and_concurrent_journal_fail(tmp_path):
    request = {"action": "snapshot", "family": "vampi", "identity": "a" * 32}
    with pytest.raises(ValueError, match="invalid declared"):
        operate({**request, "rows": []}, tmp_path)
    with pytest.raises(ValueError, match="invalid declared"):
        operate({**request, "family": "foreign"}, tmp_path)
    with patch(
        "catalog_family_recovery.database", return_value={"users": [], "books": []}
    ):
        operate(request, tmp_path)
        with pytest.raises(ValueError, match="prior recovery"):
            operate({**request, "identity": "b" * 32}, tmp_path)


def test_real_sqlite_restores_declared_actors_and_preserves_foreign_rows(tmp_path):
    file = tmp_path / "database.db"
    with sqlite3.connect(file) as database:
        database.executescript(
            "CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,email TEXT,admin BOOLEAN);CREATE TABLE books(id INTEGER PRIMARY KEY,book_title TEXT UNIQUE,secret_content TEXT,user_id INTEGER);"
        )
        database.executemany(
            "INSERT INTO users VALUES(?,?,?,?,?)",
            [
                (1, "admin", "original", "admin@example.com", True),
                (2, "unrelated", "private", "foreign@example.com", False),
            ],
        )
        database.execute("INSERT INTO books VALUES(1,'synthetic book','content',1)")
    helper = SQLITE_HELPER.replace("/vampi/database/database.db", str(file))

    def run(value):
        result = subprocess.run(  # noqa: S603 - isolated temporary SQLite fixture
            [sys.executable, "-B", "-c", helper],
            input=json.dumps(value),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    before = run({"actors": VAMPI_ACTORS, "action": "snapshot"})
    with sqlite3.connect(file) as database:
        database.execute(
            "UPDATE users SET email='changed@example.com',admin=0 WHERE id=1"
        )
        database.execute(
            "INSERT INTO users VALUES(3,'masstest1','synthetic','mass1@example.com',1)"
        )
    assert (
        run({"actors": VAMPI_ACTORS, "action": "restore", "before": before}) == before
    )
    with sqlite3.connect(file) as database:
        assert database.execute(
            "SELECT username,password,email FROM users WHERE id=2"
        ).fetchone() == ("unrelated", "private", "foreign@example.com")
        assert (
            database.execute("SELECT COUNT(*) FROM users WHERE id=3").fetchone()[0] == 0
        )


def test_sqlite_identity_collision_rolls_back_recovery(tmp_path):
    file = tmp_path / "database.db"
    with sqlite3.connect(file) as database:
        database.executescript(
            "CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,email TEXT,admin BOOLEAN);CREATE TABLE books(id INTEGER PRIMARY KEY,book_title TEXT UNIQUE,secret_content TEXT,user_id INTEGER);"
        )
        database.execute(
            "INSERT INTO users VALUES(1,'admin','original','admin@example.com',1)"
        )
    helper = SQLITE_HELPER.replace("/vampi/database/database.db", str(file))

    def run(value):
        return subprocess.run(  # noqa: S603 - isolated temporary SQLite fixture
            [sys.executable, "-B", "-c", helper],
            input=json.dumps(value),
            capture_output=True,
            text=True,
            check=False,
        )

    before = json.loads(run({"actors": VAMPI_ACTORS, "action": "snapshot"}).stdout)
    with sqlite3.connect(file) as database:
        database.execute("UPDATE users SET username='foreign' WHERE id=1")
    result = run({"actors": VAMPI_ACTORS, "action": "restore", "before": before})
    assert result.returncode != 0
    with sqlite3.connect(file) as database:
        assert (
            database.execute("SELECT username FROM users WHERE id=1").fetchone()[0]
            == "foreign"
        )
