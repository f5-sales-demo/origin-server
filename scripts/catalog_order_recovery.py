#!/usr/bin/env python3
"""Journal and restore one dedicated synthetic crAPI order and account credit."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path("/opt/origin-server/private-order-recovery")
ACTOR = "tgen-order@example.com"
MAX_INPUT = 16384


def owner() -> None:
    """Require the exact declared Compose database and Docker volume before SQL."""
    result = subprocess.run(
        ["/usr/bin/docker", "inspect", "crapi-postgres"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    data = json.loads(result.stdout)[0]
    labels = data.get("Config", {}).get("Labels", {})
    mounts = data.get("Mounts", [])
    if (
        labels.get("com.docker.compose.project") != "origin-server"
        or labels.get("com.docker.compose.service") != "crapi-postgres"
        or labels.get("com.docker.compose.project.config_files")
        != "/opt/origin-server/docker-compose.yml"
        or not any(
            m.get("Name") == "origin-server_crapi-postgres-data"
            and m.get("Destination") == "/var/lib/postgresql/data"
            for m in mounts
        )
    ):
        message = "order database ownership mismatch"
        raise ValueError(message)


def sql(statement: str, values: dict[str, str]) -> dict:
    """Pass only quoted psql variables over fixed owned database argv."""
    args = [
        "/usr/bin/docker",
        "exec",
        "-i",
        "crapi-postgres",
        "psql",
        "-U",
        "admin",
        "-d",
        "crapi",
        "-qAt",
        "-v",
        "ON_ERROR_STOP=1",
    ]
    for key, value in values.items():
        args.extend(["-v", key + "=" + value])
    result = subprocess.run(  # noqa: S603 - exact owned psql argv with quoted variables
        args, input=statement, capture_output=True, text=True, check=True, timeout=20
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def seed() -> dict:
    """Create one absent dedicated synthetic actor and order, preserving existing values."""
    owner()
    body = json.dumps({"email": ACTOR, "password": "SyntheticOrder!123"}).encode()
    request = Request(
        "http://127.0.0.1:18888/identity/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed loopback demo API
            json.load(response)
    except HTTPError as error:
        if error.code != HTTPStatus.UNAUTHORIZED:
            raise
        signup = Request(
            "http://127.0.0.1:18888/identity/api/auth/signup",
            data=json.dumps(
                {
                    "email": ACTOR,
                    "password": "SyntheticOrder!123",
                    "name": "Synthetic order actor",
                    "number": "2025550190",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(signup, timeout=20) as response:  # noqa: S310 - fixed loopback demo API
            json.load(response)
    statement = """BEGIN;
SELECT 1 / CASE WHEN (SELECT COUNT(*) FROM user_login WHERE email=:'email' AND number='2025550190')=1 THEN 1 ELSE 0 END;
INSERT INTO "order" (quantity,created_on,status,product_id,user_id,transaction_id)
SELECT 1,NOW(),'delivered',p.id,u.id,'tgen-order-fixture' FROM user_login u CROSS JOIN (SELECT id FROM product ORDER BY id LIMIT 1) p
WHERE u.email=:'email' AND NOT EXISTS(SELECT 1 FROM "order" o WHERE o.user_id=u.id);
SELECT json_build_object('order',(SELECT id FROM "order" WHERE user_id=(SELECT id FROM user_login WHERE email=:'email') ORDER BY id LIMIT 1));
COMMIT;"""
    return sql(statement, {"email": ACTOR})


def snapshot(order: int) -> dict:
    """Read immutable order ownership fields and the exact mutable baseline."""
    statement = """SELECT json_build_object('order', row_to_json(o), 'credit', d.available_credit, 'email', u.email)
FROM "order" o JOIN user_login u ON u.id=o.user_id JOIN user_details d ON d.user_id=u.id
WHERE o.id=:'order'::integer AND u.email=:'email';"""
    result = sql(statement, {"order": str(order), "email": ACTOR})
    if result.get("email") != ACTOR or result.get("order", {}).get("id") != order:
        message = "dedicated synthetic order actor mismatch"
        raise ValueError(message)
    return result


def restore(before: dict) -> dict:
    """Restore only the captured actor/order after checking immutable identity fields."""
    order = before["order"]
    statement = """BEGIN;
SELECT 1 / CASE WHEN EXISTS (SELECT 1 FROM "order" WHERE id=:'order'::integer AND user_id=:'user'::integer AND product_id=:'product'::integer AND transaction_id=:'transaction' AND created_on=:'created'::timestamp) AND EXISTS (SELECT 1 FROM user_login WHERE id=:'user'::integer AND email=:'email') THEN 1 ELSE 0 END;
UPDATE "order" SET quantity=:'quantity'::integer,status=:'status' WHERE id=:'order'::integer AND user_id=:'user'::integer;
UPDATE user_details SET available_credit=:'credit'::double precision WHERE user_id=:'user'::integer;
SELECT json_build_object('order',row_to_json(o),'credit',d.available_credit,'email',u.email) FROM "order" o JOIN user_login u ON u.id=o.user_id JOIN user_details d ON d.user_id=u.id WHERE o.id=:'order'::integer AND u.email=:'email';
COMMIT;"""
    result = sql(
        statement,
        {
            "order": str(order["id"]),
            "user": str(order["user_id"]),
            "product": str(order["product_id"]),
            "transaction": order["transaction_id"],
            "created": order["created_on"],
            "quantity": str(order["quantity"]),
            "status": order["status"],
            "credit": str(before["credit"]),
            "email": ACTOR,
        },
    )
    if result != before:
        message = "order and credit restoration readback mismatch"
        raise ValueError(message)
    return result


def operation(value: dict, directory: Path = ROOT) -> dict:
    """Use a host-only baseline journal; callers cannot supply restore values."""
    if (
        set(value) != {"action", "identity", "order"}
        or value["action"] not in ("snapshot", "restore")
        or not re.fullmatch(r"[a-f0-9]{32}", value["identity"])
    ):
        message = "invalid synthetic order journal request"
        raise ValueError(message)
    order = value["order"]
    if not isinstance(order, int) or isinstance(order, bool) or order <= 0:
        message = "invalid synthetic order journal request"
        raise ValueError(message)
    if directory.is_symlink():
        message = "unsafe order journal directory"
        raise ValueError(message)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    file = directory / (value["identity"] + ".json")
    if file.is_symlink():
        message = "unsafe order journal path"
        raise ValueError(message)
    owner()
    lock_path = directory / "order.lock"
    if lock_path.is_symlink():
        message = "unsafe order deployment lock"
        raise ValueError(message)
    with lock_path.open("a") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = directory / "active.json"
        if active.is_symlink():
            message = "unsafe active order journal"
            raise ValueError(message)
        if value["action"] == "snapshot":
            if active.exists():
                message = "another order journal requires recovery"
                raise ValueError(message)
            before = snapshot(value["order"])
            payload = {
                "identity": value["identity"],
                "order": value["order"],
                "before": before,
            }
            with file.open("x") as stream:
                file.chmod(0o600)
                json.dump(payload, stream)
            with active.open("x") as stream:
                active.chmod(0o600)
                json.dump({"identity": value["identity"]}, stream)
            return payload
        saved = json.loads(file.read_text())
        if saved["identity"] != value["identity"] or saved["order"] != value["order"]:
            message = "order journal ownership changed"
            raise ValueError(message)
        if (
            active.exists()
            and json.loads(active.read_text()).get("identity") != value["identity"]
        ):
            message = "another active order journal owns the actor"
            raise ValueError(message)
        after = restore(saved["before"])
        receipt = {**saved, "after": after, "restored": after == saved["before"]}
        if active.exists():
            active.unlink()
        return receipt


def main() -> int:
    """Accept bounded JSON only through the dedicated forced SSH operation."""
    os.umask(0o077)
    if os.environ.get("SSH_ORIGINAL_COMMAND", "") not in ("", "recover-order"):
        return 2
    if sys.argv[1:] == ["--seed"] and not os.environ.get("SSH_ORIGINAL_COMMAND"):
        print(json.dumps(seed()))
        return 0
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        return 2
    try:
        print(json.dumps(operation(json.loads(raw))))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
