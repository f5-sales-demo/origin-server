"""Recover declared RESTaurant chef/menu rows and unique catalog registrations."""

from __future__ import annotations

import base64
import json
import re
import subprocess

SUFFIXES = ("register", "customer", "ssrf", "chain")
SNAPSHOT = """
SELECT json_build_object(
 'users',COALESCE((SELECT json_agg(u ORDER BY id) FROM users u WHERE id=1),'[]'),
 'menu',COALESCE((SELECT json_agg(m ORDER BY id) FROM menu_items m WHERE id=1),'[]'),
 'temporary_users',COALESCE((SELECT json_agg(u ORDER BY id) FROM users u WHERE username = ANY({actors})),'[]')
);
"""


def actor_sql(marker: str) -> str:
    """Accept only a host-derived marker and a fixed set of registration names."""
    if not re.fullmatch(r"tgen-[a-f0-9]{32}", marker):
        message = "invalid restaurant marker"
        raise ValueError(message)
    return "ARRAY[" + ",".join("'" + marker + "-" + s + "'" for s in SUFFIXES) + "]"


def validate_snapshot(value: dict) -> None:
    """Confirm seeded row identities and reject a preoccupied actor namespace."""
    if value["temporary_users"]:
        message = "restaurant marker namespace already populated"
        raise ValueError(message)
    user_valid = (
        len(value["users"]) == 1
        and value["users"][0]["id"] == 1
        and value["users"][0]["username"] == "chef"
    )
    menu_valid = (
        len(value["menu"]) == 1
        and value["menu"][0]["id"] == 1
        and value["menu"][0]["name"] == "Pollos Classic Breakfast"
    )
    if not user_valid or not menu_valid:
        message = "restaurant declared row identity mismatch"
        raise ValueError(message)


def restore_sql(before: dict, marker: str) -> str:
    """Restore fixed captured rows, rejecting cross-user references before any deletion."""
    actors = actor_sql(marker)
    payload = base64.b64encode(json.dumps(before).encode()).decode()
    return f"""
BEGIN;
LOCK TABLE users,menu_items,orders,order_items,discount_coupons IN SHARE ROW EXCLUSIVE MODE;
DO $recovery$
DECLARE baseline jsonb := convert_from(decode('{payload}','base64'),'UTF8')::jsonb; captured users; item menu_items;
BEGIN
 IF EXISTS(SELECT 1 FROM orders WHERE user_id IN (SELECT id FROM users WHERE username = ANY({actors}))) THEN RAISE EXCEPTION 'unrelated orders'; END IF;
 IF EXISTS(SELECT 1 FROM discount_coupons WHERE user_id IN (SELECT id FROM users WHERE username = ANY({actors})) OR referrer_user_id IN (SELECT id FROM users WHERE username = ANY({actors}))) THEN RAISE EXCEPTION 'unrelated coupons'; END IF;
 captured := jsonb_populate_record(NULL::users,baseline->'users'->0);
 IF NOT EXISTS(SELECT 1 FROM users WHERE id=captured.id AND username=captured.username) THEN RAISE EXCEPTION 'actor identity changed'; END IF;
 item := jsonb_populate_record(NULL::menu_items,baseline->'menu'->0);
 IF EXISTS(SELECT 1 FROM menu_items WHERE id=item.id AND name<>item.name) THEN RAISE EXCEPTION 'menu identity changed'; END IF;
 UPDATE users SET password=captured.password,role=captured.role,first_name=captured.first_name,last_name=captured.last_name,phone_number=captured.phone_number,reset_password_code=captured.reset_password_code,reset_password_code_expiry_date=captured.reset_password_code_expiry_date,referral_code=captured.referral_code WHERE id=captured.id AND username=captured.username;
 INSERT INTO menu_items SELECT item.* ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name,description=EXCLUDED.description,price=EXCLUDED.price,category=EXCLUDED.category,image_base64=EXCLUDED.image_base64;
 DELETE FROM users WHERE username = ANY({actors});
END $recovery$;
COMMIT;
""" + SNAPSHOT.format(actors=actors)  # noqa: S608 - fixed SQL, strict marker and base64 host baseline


def restaurant_database(
    container: str, action: str, marker: str, before: dict | None = None
) -> dict:
    """Use only the owned shared PostgreSQL service and fixed journal SQL."""
    if container not in (
        "restaurant-1",
        "restaurant-2",
        "restaurant-3",
        "restaurant-4",
    ):
        message = "unknown restaurant replica"
        raise ValueError(message)
    data = json.loads(
        subprocess.check_output(
            ["/usr/bin/docker", "inspect", "restaurant-db"], text=True, timeout=10
        )
    )[0]
    labels = data.get("Config", {}).get("Labels", {})
    if (
        labels.get("com.docker.compose.project") != "origin-server"
        or labels.get("com.docker.compose.service") != "restaurant-db"
        or labels.get("com.docker.compose.project.config_files")
        != "/opt/origin-server/docker-compose.yml"
    ):
        message = "restaurant database ownership mismatch"
        raise ValueError(message)
    sql = (
        SNAPSHOT.format(actors=actor_sql(marker))
        if action == "snapshot"
        else restore_sql(before or {}, marker)
    )
    result = subprocess.run(
        [
            "/usr/bin/docker",
            "exec",
            "-i",
            "restaurant-db",
            "psql",
            "-X",
            "-q",
            "-t",
            "-A",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "admin",
            "-d",
            "restaurant",
        ],
        input=sql,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    value = json.loads(result.stdout)
    validate_snapshot(value)
    return value
