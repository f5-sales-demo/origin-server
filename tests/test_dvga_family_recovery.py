"""Native DVGA journals remove only marker-owned rows and exact upload bytes."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from catalog_dvga_recovery import NATIVE_HELPER


def test_dvga_sqlite_removes_marked_rows_and_preserves_foreign_changes(tmp_path):
    database = tmp_path / "dvga.db"
    with sqlite3.connect(database) as db:
        db.executescript(
            "CREATE TABLE pastes(id INTEGER PRIMARY KEY,user_agent TEXT,content TEXT); CREATE TABLE audits(id INTEGER PRIMARY KEY,gqloperation TEXT);"
        )
        db.execute("INSERT INTO pastes VALUES(1,'foreign','baseline')")
        db.execute("INSERT INTO audits VALUES(1,'foreign')")
    marker = "tgen-" + "a" * 32
    helper = NATIVE_HELPER.replace("/opt/dvga/dvga.db", str(database)).replace(
        "/opt/dvga/uploads/", str(tmp_path / "uploads") + "/"
    )

    def run(action):
        result = subprocess.run(  # noqa: S603 - fixed isolated native SQLite helper
            [sys.executable, "-B", "-c", helper],
            input=json.dumps({"action": action, "marker": marker}),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    assert run("snapshot") == {"pastes": [], "audits": [], "files": {}}
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO pastes VALUES(2,?, 'owned')", (marker,))
        db.execute("INSERT INTO audits VALUES(2,?)", (marker,))
        db.execute("UPDATE pastes SET content='unrelated change' WHERE id=1")
    assert run("restore") == {"pastes": [], "audits": [], "files": {}}
    with sqlite3.connect(database) as db:
        assert (
            db.execute("SELECT content FROM pastes WHERE id=1").fetchone()[0]
            == "unrelated change"
        )
        assert db.execute("SELECT COUNT(*) FROM audits").fetchone()[0] == 1


def test_declared_adapter_marks_native_paste_and_audit_writes():
    files = json.loads(
        (Path(__file__).parents[1] / "provisioning/files.json").read_text()
    )
    source = next(
        r["content"] for r in files if r["path"].endswith("dvga-adapter/adapt.py")
    )
    assert 'kw["user_agent"] = marker' in source
    assert "entry.gqloperation = marker" in source
    assert "X-TGen-Family" in source
