#!/usr/bin/env python3
"""Verify issued authentication and seeded application workflows at each serving layer."""

import argparse
import http.cookiejar
import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SUCCESS_MIN, SUCCESS_MAX = 200, 300


def require(condition: bool, message: str) -> None:
    """Fail a required application content assertion."""
    if not condition:
        raise ValueError(message)


def issued_token(value: dict, key: str) -> str:
    """Require a real nonempty application-issued token."""
    token = value.get(key)
    if not isinstance(token, str) or not token:
        message = "application-issued token missing"
        raise ValueError(message)
    return token


def complete_report(report: dict, expected: set[str]) -> bool:
    """Require every declared application and every workflow result."""
    checks = report.get("checks", [])
    return (
        bool(checks)
        and {check["application"] for check in checks} == expected
        and all(check["passed"] for check in checks)
    )


def json_content_type(value: str, accepted: set[str]) -> bool:
    """Accept only route-declared JSON MIME types, never HTML landing content."""
    return value in accepted


class Client:
    """A bounded HTTP client with an isolated cookie jar per workflow."""

    def __init__(self, base: str) -> None:
        """Create application-local authentication state."""
        self.base = base.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def request(
        self,
        path: str,
        data: dict | None = None,
        token: str | None = None,
        form: bool = False,
    ) -> tuple[str, str]:
        """Read successful responses with identity and content-type assertions at callers."""
        headers = {"X-MUD-User": "waap-workflow-benign"}
        payload = None
        if data is not None:
            payload = urlencode(data).encode() if form else json.dumps(data).encode()
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded" if form else "application/json"
            )
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(self.base + path, data=payload, headers=headers)  # noqa: S310 - validated HTTP serving layers
        with self.opener.open(request, timeout=10) as response:
            require(
                SUCCESS_MIN <= response.status < SUCCESS_MAX,
                "unexpected workflow status",
            )
            body = response.read(MAX_RESPONSE_BYTES + 1)
            require(len(body) <= MAX_RESPONSE_BYTES, "oversized workflow response")
            return response.headers.get_content_type(), body.decode()

    def document(
        self,
        path: str,
        data: dict | None = None,
        token: str | None = None,
        form: bool = False,
    ) -> dict:
        """Require a real JSON document rather than a successful landing response."""
        content_type, body = self.request(path, data, token, form)
        accepted = (
            {"application/json", "text/json"}
            if path.startswith("/mailhog/")
            else {"application/json"}
        )
        require(
            json_content_type(content_type, accepted),
            "workflow JSON content type mismatch",
        )
        value = json.loads(body)
        require(isinstance(value, dict), "workflow JSON identity mismatch")
        return value


def verify_vampi(client: Client) -> list[str]:
    """Verify API identity, authentication and seeded user/book objects."""
    require(
        "VAmPI" in client.document("/").get("message", ""), "VAmPI identity mismatch"
    )
    require("openapi" in client.document("/openapi.json"), "VAmPI definition missing")
    token = issued_token(
        client.document("/users/v1/login", {"username": "name1", "password": "pass1"}),
        "auth_token",
    )
    require(
        bool(client.document("/users/v1", token=token).get("users")),
        "VAmPI seeded users missing",
    )
    require(
        bool(client.document("/books/v1", token=token).get("Books")),
        "VAmPI seeded books missing",
    )
    return ["api-definition", "authentication", "users", "seeded-books"]


def verify_juice(client: Client, fixtures: dict) -> list[str]:
    """Verify translations, products, issued login and the corresponding basket."""
    require(
        bool(client.document("/assets/i18n/en.json").get("TITLE_LOGIN")),
        "translation labels missing",
    )
    require(
        bool(client.document("/rest/products/search").get("data")),
        "Juice products missing",
    )
    authentication = client.document(
        "/rest/user/login",
        {"email": fixtures["juice_email"], "password": fixtures["juice_password"]},
    ).get("authentication", {})
    token = issued_token(authentication, "token")
    require(authentication.get("bid") is not None, "issued basket identity missing")
    basket = client.document("/rest/basket/" + str(authentication["bid"]), token=token)
    require(isinstance(basket.get("data"), dict), "issued basket response missing")
    return ["translated-labels", "products", "login", "basket"]


def verify_restaurant(client: Client, role: str) -> list[str]:
    """Verify same-origin API definition and each seeded role's own profile."""
    definition = client.document("/openapi.json")
    require(
        any(
            server.get("url") == "/restaurant"
            for server in definition.get("servers", [])
        ),
        "OpenAPI published server mismatch",
    )
    token = issued_token(
        client.document(
            "/token", {"username": "tgen_" + role, "password": "password"}, form=True
        ),
        "access_token",
    )
    profile = client.document("/profile", token=token)
    require(
        profile.get("username") == "tgen_" + role, "authenticated role profile mismatch"
    )
    require(str(profile.get("role", "")).lower() == role, "seeded role mismatch")
    return ["same-origin-definition", "authentication", "seeded-" + role]


def verify_crapi(client: Client) -> list[str]:
    """Verify a seeded account's vehicle, community, workshop and local MailHog route."""
    token = issued_token(
        client.document(
            "/identity/api/auth/login",
            {"email": "adam007@example.com", "password": "adam007!123"},
        ),
        "token",
    )
    content_type, body = client.request(
        "/identity/api/v2/vehicle/vehicles", token=token
    )
    vehicles = json.loads(body)
    require(
        content_type == "application/json"
        and isinstance(vehicles, list)
        and bool(vehicles),
        "seeded vehicles missing",
    )
    require(
        bool(
            client.document(
                "/community/api/v2/community/posts/recent?limit=1&offset=0", token=token
            ).get("posts")
        ),
        "seeded community missing",
    )
    require(
        bool(
            client.document("/workshop/api/shop/products", token=token).get("products")
        ),
        "seeded workshop missing",
    )
    require(
        "items" in client.document("/mailhog/api/v2/messages"), "MailHog route mismatch"
    )
    return ["login", "seeded-vehicle", "community", "workshop", "mailhog"]


def verify_dvwa(client: Client) -> list[str]:
    """Verify login and seeded vulnerability page content with actual session cookies."""
    _, login = client.request("/login.php")
    token = re.search(r"name=['\"]user_token['\"].*?value=['\"]([^'\"]+)", login)
    if token is None:
        message = "DVWA login token missing"
        raise ValueError(message)
    _, body = client.request(
        "/login.php",
        {
            "username": "admin",
            "password": "password",
            "Login": "Login",
            "user_token": token[1],
        },
        form=True,
    )
    require("Logout" in body, "DVWA authentication missing")
    for path in [
        "/index.php",
        "/security.php",
        "/vulnerabilities/sqli/",
        "/vulnerabilities/xss_r/",
    ]:
        content_type, body = client.request(path)
        require(
            content_type == "text/html" and "DVWA" in body and "Logout" in body,
            "DVWA authenticated page identity mismatch",
        )
    return [
        "authenticated-navigation",
        "security-settings",
        "seeded-vulnerability-pages",
    ]


def main() -> int:
    """Verify declared native replicas or one published application map."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base")
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    require(args.native != bool(args.base), "choose native or a published base")
    manifest = json.loads(args.manifest.read_text())
    fixtures = json.loads(args.fixtures.read_text())
    checks = []
    supported = {"juice-shop", "dvwa", "vampi", "restaurant", "crapi"}
    for app in manifest["applications"]:
        if app["id"] not in supported:
            continue
        bases = (
            ["http://127.0.0.1:" + str(port) for port in app["ports"]]
            if args.native
            else [args.base.rstrip("/") + app["prefix"].rstrip("/")]
        )
        for base in bases:
            check = {"application": app["id"], "layer": base, "passed": False}
            try:
                client = Client(base)
                if app["id"] == "juice-shop":
                    assertions = verify_juice(client, fixtures)
                elif app["id"] == "dvwa":
                    assertions = verify_dvwa(client)
                elif app["id"] == "vampi":
                    assertions = verify_vampi(client)
                elif app["id"] == "restaurant":
                    assertions = verify_restaurant(
                        client, "customer"
                    ) + verify_restaurant(client, "chef")
                else:
                    assertions = verify_crapi(client)
                check.update(passed=True, assertions=assertions)
            except (OSError, ValueError, KeyError, TypeError) as error:
                check["error"] = type(error).__name__
            checks.append(check)
    report = {
        "schema_version": 1,
        "checked": time.time(),
        "checks": checks,
        "complete_application_acceptance": False,
    }
    report["supported_workflows_passed"] = complete_report(report, supported)
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    args.output.chmod(0o600)
    print(
        json.dumps(
            {
                "supported_workflows_passed": report["supported_workflows_passed"],
                "checks": len(checks),
                "failures": sum(not check["passed"] for check in checks),
            }
        )
    )
    return int(not report["supported_workflows_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
