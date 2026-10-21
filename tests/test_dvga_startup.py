"""Protect native SQLite fixtures across ordinary DVGA startup."""

import sqlite3
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
initialize_database = import_module("dvga_startup").initialize_database
render = import_module("render_origin").render


def native_setup(root):
    setup = root / "setup.py"
    setup.write_text(
        "import sqlite3\n"
        "from pathlib import Path\n"
        "db = Path('dvga.db')\n"
        "db.unlink(missing_ok=True)\n"
        "with sqlite3.connect(db) as connection:\n"
        " for table in ['users', 'pastes', 'audits']:\n"
        "  connection.execute('CREATE TABLE ' + table + ' (id INTEGER, value TEXT)')\n"
        " connection.execute(\"INSERT INTO pastes VALUES (1, 'native seed')\")\n"
    )
    return setup


def test_absent_database_uses_native_setup_once_and_preserves_records(tmp_path):
    setup = native_setup(tmp_path)
    database = tmp_path / "dvga.db"
    assert initialize_database(database, setup) is True
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO pastes VALUES (2, 'synthetic persistent record')"
        )
    before = database.read_bytes()
    assert initialize_database(database, setup) is False
    assert initialize_database(database, setup) is False
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pastes").fetchone() == (2,)


def test_explicit_native_reset_remains_available(tmp_path):
    setup = native_setup(tmp_path)
    database = tmp_path / "dvga.db"
    initialize_database(database, setup)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO pastes VALUES (2, 'synthetic persistent record')"
        )
    subprocess.run(  # noqa: S603 - exact synthetic native reset fixture
        [sys.executable, str(setup)], cwd=tmp_path, check=True
    )
    assert initialize_database(database, setup) is False
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pastes").fetchone() == (1,)


@pytest.mark.parametrize(
    "kind", ["empty", "corrupt", "directory", "symlink", "missing_schema"]
)
def test_existing_invalid_database_fails_without_reset(tmp_path, kind):
    setup = native_setup(tmp_path)
    database = tmp_path / "dvga.db"
    if kind == "directory":
        database.mkdir()
    elif kind == "symlink":
        target = tmp_path / "independent.db"
        target.write_bytes(b"independent synthetic bytes")
        database.symlink_to(target)
    elif kind == "missing_schema":
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE unrelated (id INTEGER)")
    else:
        database.write_bytes(b"" if kind == "empty" else b"invalid synthetic bytes")
    before = database.read_bytes() if database.is_file() else None
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        initialize_database(database, setup)
    if before is not None:
        assert database.read_bytes() == before
    if kind == "symlink":
        assert database.is_symlink()


def test_native_setup_failure_propagates(tmp_path):
    setup = tmp_path / "setup.py"
    setup.write_text("raise SystemExit(7)\n")
    with pytest.raises(subprocess.CalledProcessError) as error:
        initialize_database(tmp_path / "dvga.db", setup)
    assert error.value.returncode == 7
    assert not (tmp_path / "dvga.db").exists()


def test_successful_setup_without_native_schema_is_rejected(tmp_path):
    setup = tmp_path / "setup.py"
    setup.write_text("pass\n")
    with pytest.raises(ValueError, match="did not create"):
        initialize_database(tmp_path / "dvga.db", setup)


def test_declared_adapter_changes_startup_only():
    files = {entry["path"]: entry["content"] for entry in render(ROOT)}
    assert (
        files["/opt/origin-server/dvga-adapter/dvga_startup.py"]
        == (ROOT / "scripts/dvga_startup.py").read_text()
    )
    assert (
        "COPY dvga_startup.py /opt/dvga/dvga_startup.py"
        in files["/opt/origin-server/dvga-adapter/Dockerfile"]
    )
    adapter = files["/opt/origin-server/dvga-adapter/adapt.py"]
    assert 'os.popen("python3 setup.py").read()' in adapter
    assert "initialize_database(config.SQLALCHEMY_FILE" in adapter
    assert "setup.py').write_text" not in adapter
