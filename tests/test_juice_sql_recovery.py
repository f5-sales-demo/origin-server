"""Real SQLite recovery preserves foreign rows and rolls back identity collisions."""

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from catalog_juice_recovery import NODE_SQL


def seed(path):
    with sqlite3.connect(path) as db:
        db.executescript("""
CREATE TABLE Users(id INTEGER PRIMARY KEY,email TEXT,password TEXT,lastLoginIp TEXT,profileImage TEXT,updatedAt TEXT);
CREATE TABLE Feedbacks(id INTEGER PRIMARY KEY,UserId INTEGER,comment TEXT,rating INTEGER,updatedAt TEXT);
CREATE TABLE Baskets(id INTEGER PRIMARY KEY,UserId INTEGER);
CREATE TABLE BasketItems(id INTEGER PRIMARY KEY,ProductId INTEGER,BasketId INTEGER,quantity INTEGER,createdAt TEXT,updatedAt TEXT);
CREATE TABLE SecurityAnswers(UserId INTEGER);
""")
        for table in [
            "Addresses",
            "Cards",
            "Complaints",
            "Memories",
            "PrivacyRequests",
            "Recycles",
        ]:
            db.execute("CREATE TABLE " + table + "(UserId INTEGER)")
        db.execute("CREATE TABLE Wallets(UserId INTEGER,balance INTEGER)")
        for i, email in enumerate(
            ["admin@example.com", "jim@example.com", "bender@example.com"], 1
        ):
            db.execute(
                "INSERT INTO Users VALUES(?,?,?,?,?,?)",
                (i, email, "original", "127.0.0.1", "default.svg", "original"),
            )
            db.execute("INSERT INTO Baskets VALUES(?,?)", (i, i))
            db.execute(
                "INSERT INTO Feedbacks VALUES(?,?,?,?,?)",
                (i, i, "original", 5, "original"),
            )
        db.execute(
            "INSERT INTO Users VALUES(99,'foreign@example.com','private','foreign','foreign','foreign')"
        )


def test_real_sqlite_restores_owned_rows_and_preserves_unrelated_rows(tmp_path):
    db = tmp_path / "juice.sqlite"
    seed(db)
    marker = "tgen-" + "a" * 32
    sqlite = """(()=>{const {DatabaseSync}=require('node:sqlite');return {Database:class {
constructor(path){this.db=new DatabaseSync(path)}
all(sql,args,callback){try{callback(null,this.db.prepare(sql).all(...args))}catch(error){callback(error)}}
run(sql,args,callback){try{this.db.prepare(sql).run(...args);callback(null)}catch(error){callback(error)}}
close(){this.db.close()}
}}})()"""
    profile = tmp_path / "profile"
    profile.mkdir()
    helper = (
        NODE_SQL.replace("/juice-shop/data/juiceshop.sqlite", str(db))
        .replace("require('/juice-shop/node_modules/sqlite3')", sqlite)
        .replace(
            "/juice-shop/frontend/dist/frontend/assets/public/images/uploads",
            str(profile),
        )
    )

    def run(value):
        result = subprocess.run(  # noqa: S603 - fixed isolated SQLite helper
            [shutil.which("node") or "/usr/bin/node", "-e", helper],
            input=json.dumps(value),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    before = run({"action": "snapshot", "marker": marker})
    with sqlite3.connect(db) as sql:
        sql.execute(
            "UPDATE Feedbacks SET comment=?,rating=1 WHERE id=1", (marker + ":changed",)
        )
        sql.execute(
            "INSERT INTO Users VALUES(100,?,'synthetic','0.0.0.0','default','new')",
            (marker + "@example.com",),
        )
        sql.execute("INSERT INTO Baskets VALUES(100,100)")
        sql.execute("INSERT INTO Wallets VALUES(100,0)")
        sql.execute("INSERT INTO BasketItems VALUES(1,1,1,1,'new','new')")
        sql.execute(
            "INSERT INTO Feedbacks VALUES(100,1,?,3,'new')", (marker + ":payload",)
        )
    assert run({"action": "restore", "marker": marker, "before": before}) == before
    with sqlite3.connect(db) as sql:
        assert (
            sql.execute("SELECT password FROM Users WHERE id=99").fetchone()[0]
            == "private"
        )
        sql.execute("UPDATE Users SET email='foreign-collision@example.com' WHERE id=1")
    with pytest.raises(subprocess.CalledProcessError):
        run({"action": "restore", "marker": marker, "before": before})
    with sqlite3.connect(db) as sql:
        assert (
            sql.execute("SELECT email FROM Users WHERE id=1").fetchone()[0]
            == "foreign-collision@example.com"
        )
