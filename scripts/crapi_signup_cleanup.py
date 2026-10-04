"""Recover only a journaled synthetic signup account, welcome vehicle and mail message."""

import json
import re
import subprocess
from email import policy
from email.parser import Parser
from email.utils import getaddresses
from pathlib import Path
from urllib.request import Request, urlopen


def discover_welcome(journal: dict) -> None:
    """Find the exact welcome message and decode its MIME vehicle identity."""
    email = journal["email"]
    with urlopen(
        "http://127.0.0.1:18888/mailhog/api/v2/messages?limit=1000", timeout=20
    ) as response:
        messages = json.load(response)["items"]
    owned_mail = [
        item
        for item in messages
        if email
        in {
            address
            for _, address in getaddresses(
                item.get("Content", {}).get("Headers", {}).get("To", [])
            )
        }
    ]
    welcome = []
    for message in owned_mail:
        parsed = Parser(policy=policy.default).parsestr(message["Raw"]["Data"])
        parts = parsed.walk() if parsed.is_multipart() else [parsed]
        body = "\n".join(
            part.get_content()
            for part in parts
            if part.get_content_type() in ("text/plain", "text/html")
        )
        found = re.search(r"VIN:[\s\S]*?>([A-HJ-NPR-Z0-9]{17})<", body)
        if found:
            welcome.append(found[1])
        elif parsed.get("Subject") != "crAPI OTP":
            error = "unrecognized owned signup mail"
            raise ValueError(error)
    if len(welcome) > 1:
        error = "ambiguous signup vehicle ownership"
        raise ValueError(error)
    if welcome:
        if journal.get("vehicle_vin") not in (None, welcome[0]):
            error = "journaled vehicle ownership changed"
            raise ValueError(error)
        journal["vehicle_vin"] = welcome[0]
    journal["mail_ids"] = sorted(
        set(journal.get("mail_ids", [])) | {item["ID"] for item in owned_mail}
    )


def recover_signup(output: Path) -> dict:
    """Require exact account ownership and confirmed vehicle/mail identity before removal."""
    journal = json.loads((output / "fixture-journal.json").read_text())
    email = journal["email"]
    number = journal["number"]
    if not re.fullmatch(r"signup-[a-f0-9]{32}@example\.com", email) or not re.fullmatch(
        r"555[0-9]{7}", number
    ):
        message = "synthetic signup identity invalid"
        raise ValueError(message)
    discover_welcome(journal)
    (output / "fixture-journal.json").write_text(json.dumps(journal))
    vin = journal.get("vehicle_vin")
    if vin is not None and not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
        message = "synthetic welcome VIN invalid"
        raise ValueError(message)
    sql = """BEGIN;
SELECT 1 / CASE WHEN EXISTS (SELECT 1 FROM user_login WHERE email=:'email' AND number<>:'number') THEN 0 ELSE 1 END;
DELETE FROM otp WHERE user_id IN (SELECT id FROM user_login WHERE email=:'email' AND number=:'number');
SELECT 1 / CASE WHEN EXISTS (SELECT 1 FROM vehicle_details WHERE vin=:'vin' AND owner_id IS NOT NULL AND owner_id NOT IN (SELECT id FROM user_login WHERE email=:'email' AND number=:'number')) THEN 0 ELSE 1 END;
DELETE FROM vehicle_details WHERE vin=:'vin' AND (owner_id IS NULL OR owner_id IN (SELECT id FROM user_login WHERE email=:'email' AND number=:'number'));
DELETE FROM user_details WHERE user_id IN (SELECT id FROM user_login WHERE email=:'email' AND number=:'number');
DELETE FROM user_login WHERE email=:'email' AND number=:'number';
SELECT (SELECT COUNT(*) FROM user_login WHERE email=:'email') + (SELECT COUNT(*) FROM vehicle_details WHERE vin=:'vin');
COMMIT;"""
    process = subprocess.run(  # noqa: S603 - exact owned database argv with psql quoted variables
        [
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
            "-v",
            "email=" + email,
            "-v",
            "number=" + number,
            "-v",
            "vin=" + (vin or ""),
        ],
        input=sql,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    if process.stdout.strip().splitlines()[-1:] != ["0"]:
        message = "signup account recovery failed"
        raise ValueError(message)
    for mail_id in journal.get("mail_ids", []):
        if not re.fullmatch(r"[A-Za-z0-9@._=+-]+", mail_id):
            message = "mail fixture identifier invalid"
            raise ValueError(message)
        request = Request(
            "http://127.0.0.1:18888/mailhog/api/v1/messages/" + mail_id, method="DELETE"
        )
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed loopback MailHog
            if response.status not in (200, 204):
                message = "mail recovery failed"
                raise ValueError(message)
    with urlopen(
        "http://127.0.0.1:18888/mailhog/api/v2/messages?limit=1000", timeout=20
    ) as response:
        remaining = json.load(response)["items"]
    if any(item["ID"] in journal.get("mail_ids", []) for item in remaining):
        message = "signup mail remains after recovery"
        raise ValueError(message)
    receipt = {
        "account_removed": True,
        "vehicle_identified": bool(vin),
        "mail_removed": len(journal.get("mail_ids", [])),
        "passed": bool(vin) and bool(journal.get("mail_ids")),
    }
    path = output / "fixture-recovery-receipt.json"
    path.write_text(json.dumps(receipt))
    path.chmod(0o600)
    return receipt
