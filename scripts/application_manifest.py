#!/usr/bin/env python3
"""Validate the shared application inventory and derive published endpoints."""

import argparse
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_PORT = 65535
APPLICATION_IDS = frozenset(
    {
        "juice-shop",
        "dvwa",
        "vampi",
        "httpbin",
        "whoami",
        "csd-demo",
        "dvga",
        "restaurant",
        "crapi",
    }
)


def validate_manifest(manifest: dict) -> None:
    """Reject incomplete applications, prefix escapes and conflicting native ports."""
    if manifest.get("schema_version") != 1:
        message = "unsupported application manifest schema"
        raise ValueError(message)
    applications = manifest.get("applications", [])
    if (
        len(applications) != len(APPLICATION_IDS)
        or {app["id"] for app in applications} != APPLICATION_IDS
    ):
        message = (
            "application inventory must contain exactly the nine agreed applications"
        )
        raise ValueError(message)
    ports = []
    for app in applications:
        if app["prefix"] != "/" + app["id"] + "/":
            message = "application prefix does not match the published contract"
            raise ValueError(message)
        if (
            len(app["ports"]) != app["replicas"]
            or not app["pages"]
            or not app["workflows"]
        ):
            message = "replica, content or workflow contract missing"
            raise ValueError(message)
        ports.extend(app["ports"])
        for page in app["pages"]:
            path = unquote(page["path"])
            parsed = urlsplit(path)
            if (
                path.startswith("/")
                or parsed.scheme
                or parsed.netloc
                or ".." in path.split("/")
                or "\\" in path
            ):
                message = "page escapes its application prefix"
                raise ValueError(message)
            if not page["content_type"] or not page["identity"]:
                message = "page content identity and type must be explicit"
                raise ValueError(message)
    if len(set(ports)) != len(ports) or any(
        isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= MAX_PORT
        for port in ports
    ):
        message = "invalid or conflicting native replica ports"
        raise ValueError(message)


def load_manifest(path: Path) -> dict:
    """Read and strictly validate the source inventory."""
    manifest = json.loads(path.read_text())
    validate_manifest(manifest)
    return manifest


def url_map(manifest: dict, base: str) -> dict[str, str]:
    """Generate published application URLs from one manifest."""
    validate_manifest(manifest)
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
    ):
        message = "application base must be an HTTP(S) origin"
        raise ValueError(message)
    return {
        app["id"]: base.rstrip("/") + app["prefix"] for app in manifest["applications"]
    }


def content_matches(page: dict, content_type: str, body: str) -> bool:
    """A successful status alone cannot substitute for expected content."""
    return (
        content_type.split(";", 1)[0].strip().lower() == page["content_type"].lower()
        and page["identity"].casefold() in body.casefold()
    )


def main() -> int:
    """Validate inventory and emit generated application URLs."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "provisioning/applications.json",
    )
    parser.add_argument("--base", default="http://127.0.0.1")
    args = parser.parse_args()
    print(json.dumps(url_map(load_manifest(args.manifest), args.base), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
