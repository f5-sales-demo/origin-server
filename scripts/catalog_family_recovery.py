#!/usr/bin/env python3
"""Recover exact declared VAmPI demo rows from a private host journal."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from catalog_dvga_recovery import dvga_database
from catalog_dvwa_recovery import dvwa_database
from catalog_juice_recovery import juice_database
from catalog_restaurant_recovery import restaurant_database

JOURNALS = Path("/opt/origin-server/private-family-journals")
VAMPI_ACTORS = [
    "admin",
    "attacker",
    "masstest1",
    "masstest2",
    "masstest3",
    "masstest4",
    "massput",
]
MAX_INPUT = 16384
SQLITE_HELPER = r"""
import sqlite3,json,sys
value=json.load(sys.stdin)
c=sqlite3.connect('/vampi/database/database.db');c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE')
actors=value['actors'];marks=','.join('?' for _ in actors)
def snapshot():
 users=[dict(r) for r in c.execute('SELECT * FROM users WHERE username IN ('+marks+') ORDER BY id',actors)]
 ids=[r['id'] for r in users]
 books=[dict(r) for r in c.execute('SELECT * FROM books WHERE user_id IN ('+','.join('?' for _ in ids)+') ORDER BY id',ids)] if ids else []
 return {'users':users,'books':books}
if value['action']=='snapshot': result=snapshot()
else:
 before=value['before'];current=snapshot();original={r['id']:r for r in before['users']}
 for row in current['users']:
  if row['username'] not in actors:raise ValueError('unowned actor')
  if row['id'] in original and row['username']!=original[row['id']]['username']:raise ValueError('actor identity changed')
  if row['id'] not in original:
   if row['username'] in [r['username'] for r in before['users']]:raise ValueError('actor replacement ambiguous')
   if row['username'] not in ['masstest1','masstest2','masstest3','masstest4','massput']:raise ValueError('new actor outside registration corpus')
   if c.execute('SELECT COUNT(*) FROM books WHERE user_id=?',(row['id'],)).fetchone()[0]:raise ValueError('new actor has unrelated books')
   c.execute('DELETE FROM users WHERE id=? AND username=?',(row['id'],row['username']))
 for row in before['users']:
  collision=c.execute('SELECT username FROM users WHERE id=?',(row['id'],)).fetchone()
  if collision and collision[0]!=row['username']:raise ValueError('foreign user ID collision')
  c.execute('INSERT OR REPLACE INTO users(id,username,password,email,admin) VALUES(?,?,?,?,?)',tuple(row[k] for k in ['id','username','password','email','admin']))
 for row in before['books']:
  collision=c.execute('SELECT book_title FROM books WHERE id=?',(row['id'],)).fetchone()
  if collision and collision[0]!=row['book_title']:raise ValueError('foreign book collision')
  c.execute('INSERT OR REPLACE INTO books(id,book_title,secret_content,user_id) VALUES(?,?,?,?)',tuple(row[k] for k in ['id','book_title','secret_content','user_id']))
 result=snapshot()
 if result!=before:raise ValueError('VAmPI recovery mismatch')
c.commit();print(json.dumps(result))
"""


def database(container: str, action: str, before: dict | None = None) -> dict:
    """Verify exact Compose ownership before accessing a declared replica database."""
    data = json.loads(
        subprocess.check_output(  # noqa: S603 - declared owned Docker inventory
            ["/usr/bin/docker", "inspect", container], text=True, timeout=10
        )
    )[0]
    labels = data.get("Config", {}).get("Labels", {})
    if (
        labels.get("com.docker.compose.project") != "origin-server"
        or labels.get("com.docker.compose.service") != container
        or labels.get("com.docker.compose.project.config_files")
        != "/opt/origin-server/docker-compose.yml"
    ):
        message = "VAmPI replica ownership mismatch"
        raise ValueError(message)
    result = subprocess.run(  # noqa: S603 - verified SQLite helper and structured input
        [
            "/usr/bin/docker",
            "exec",
            "-i",
            container,
            "python3",
            "-B",
            "-c",
            SQLITE_HELPER,
        ],
        input=json.dumps({"actors": VAMPI_ACTORS, "action": action, "before": before}),
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    return json.loads(result.stdout)


def family_database(
    name: str, family: str, action: str, marker: str, before: dict | None = None
) -> dict:
    """Dispatch only fixed family-specific native recovery adapters."""
    if family == "vampi":
        return database(name, action, before)
    if family == "dvwa":
        return dvwa_database(name, action, marker)
    if family == "restaurant":
        return restaurant_database(name, action, marker, before)
    if family == "juice-shop":
        return juice_database(name, action, marker, before)
    return dvga_database(name, action, marker)


def operate(value: dict, root: Path = JOURNALS) -> dict:
    """Require a fixed family and host-owned baseline; never accept caller SQL or rows."""
    if (
        set(value) != {"action", "identity", "family"}
        or value["action"] not in ("snapshot", "restore")
        or value["family"] not in ("vampi", "dvwa", "restaurant", "juice-shop", "dvga")
        or not re.fullmatch(r"[a-f0-9]{32}", value["identity"])
    ):
        message = "invalid declared family journal"
        raise ValueError(message)
    if any(p.is_symlink() for p in (root, *root.parents)):
        message = "unsafe family journal path"
        raise ValueError(message)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / (value["identity"] + ".json")
    family = value["family"]
    marker = "tgen-" + value["identity"]
    active = root / (family + ".active.json")
    lock_path = root / (family + ".lock")
    if any(p.is_symlink() for p in [path, active, lock_path]):
        message = "unsafe family journal artifact"
        raise ValueError(message)
    with lock_path.open("a") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if value["action"] == "snapshot":
            if active.exists():
                message = "catalog family requires prior recovery"
                raise ValueError(message)
            baseline = {
                "identity": value["identity"],
                "family": family,
                "marker": marker,
                "replicas": {
                    name: family_database(name, family, "snapshot", marker)
                    for name in [family + "-" + str(i) for i in range(1, 5)]
                },
            }
            with path.open("x") as stream:
                path.chmod(0o600)
                json.dump(baseline, stream)
            with active.open("x") as stream:
                active.chmod(0o600)
                json.dump({"identity": value["identity"]}, stream)
            return baseline
        baseline = json.loads(path.read_text())
        if (
            baseline["identity"] != value["identity"]
            or baseline["family"] != family
            or (
                active.exists()
                and json.loads(active.read_text())["identity"] != value["identity"]
            )
        ):
            message = "family journal identity changed"
            raise ValueError(message)
        after = {
            name: family_database(name, family, "restore", marker, before)
            for name, before in baseline["replicas"].items()
        }
        if after != baseline["replicas"]:
            message = "replica recovery mismatch"
            raise ValueError(message)
        if active.exists():
            active.unlink()
        return {**baseline, "after": after, "restored": True}


def main() -> int:
    """Permit bounded structured journal operations through one forced SSH command."""
    os.umask(0o077)
    if os.environ.get("SSH_ORIGINAL_COMMAND", "") not in ("", "recover-family"):
        return 2
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        return 2
    try:
        print(json.dumps(operate(json.loads(raw))))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
