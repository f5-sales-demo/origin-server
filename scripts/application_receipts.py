"""Join current-source workflow evidence without accepting partial browser or HTTP slices."""

import argparse
import hashlib
import json
import re
import subprocess
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

DOMAIN_COUNT = 2
HTTP_SUCCESS = 200
SHA256_LENGTH = 64

BROWSER_WORKFLOWS = {
    "juice": {
        "products-and-images": {"products", "product-images"},
        "translated-labels": {"login-labels"},
        "login": {"native-login"},
        "basket": {"seeded-basket"},
        "supporting-pages": {"about", "contact", "recycle", "complain", "score-board"},
        "socket-io-affinity": set(),
    },
    "dvwa": {
        "authenticated-navigation": {"authenticated-home"},
        "styles-and-forms": {
            "authenticated-home",
            "security-form",
            "seeded-sql-page",
            "reflected-form",
        },
        "security-settings": {"security-form"},
        "seeded-vulnerability-pages": {"seeded-sql-page", "reflected-form"},
    },
    "httpbin": {
        "local-swagger-assets": {"swagger"},
        "specification": {"specification"},
        "links-and-forms": {"native-form", "echoed-form"},
    },
    "csd": {
        "dashboard": {"dashboard"},
        "checkout": {"checkout", "checkout-complete"},
        "receiver": {"receiver-counter"},
        "counter": {"receiver-counter"},
        "clear-log": {"scoped-clear"},
    },
    "dvga": {
        "styles-scripts-images": {"home", "public-pastes", "create-form"},
        "navigation-and-forms": {
            "home",
            "create-form",
            "created-paste",
            "persisted-paste",
        },
        "graphql": {"created-paste", "persisted-paste"},
        "subscriptions": {"subscription-delivery"},
        "seeded-pastes": {"public-pastes"},
    },
    "restaurant": {
        "swagger": {"swagger-customer", "swagger-chef"},
        "redoc": {"redoc"},
        "local-assets": {"swagger-customer", "redoc"},
        "authentication": {"profile-customer", "profile-chef"},
        "seeded-roles": {"profile-customer", "profile-chef"},
    },
    "crapi-signup": {
        "signup": {
            "signup-submit",
            "signup-mailhog",
            "signup-login",
            "signup-vehicle",
            "reset-mailhog",
            "reset-password-login",
        },
        "mailhog": {"mailhog-render"},
    },
    "crapi": {
        "login": {"vehicle"},
        "seeded-vehicle": {"vehicle"},
        "community": {"Community", "Community-refresh"},
        "workshop": {"workshop-form", "Shop", "Shop-refresh"},
        "deep-link-refresh": {"Community-refresh", "Shop-refresh"},
    },
}


def browser_assertions(
    kind: str, receipt: dict, runtime: dict, provenance: dict, base: str
) -> set[str]:
    """Require matching source, serving layer, successful runtime and concrete check evidence."""
    gates = [
        runtime.get("source_commit") == provenance.get("source_commit"),
        runtime.get("archive_sha256") == provenance.get("archive_sha256"),
        runtime.get("base") == base,
        runtime.get("kind") == kind,
        isinstance(runtime.get("verifier_sha256"), str)
        and len(runtime["verifier_sha256"]) == SHA256_LENGTH,
        runtime.get("exit_code") == 0,
        runtime.get("cleanup") is True,
        receipt.get("passed") is True,
        receipt.get("browser_closed") is True,
        not receipt.get("errors"),
        bool(receipt.get("checks")),
        all(check.get("passed") is True for check in receipt.get("checks", [])),
        kind not in {"dvga", "csd"} or receipt.get("fixture_restored") is True,
        kind != "crapi-signup"
        or runtime.get("fixture_recovery", {}).get("passed") is True,
    ]
    if not all(gates):
        return set()
    checks = {check["name"] for check in receipt["checks"]}
    covered = {
        workflow
        for workflow, required in BROWSER_WORKFLOWS.get(kind, {}).items()
        if required and required <= checks
    }
    if kind == "juice" and receipt.get("websocket_frames", 0) > 0:
        covered.add("socket-io-affinity")
    return covered


def coverage_matrix(manifest: dict, observations: list[dict]) -> dict:
    """Require every native replica and four published layers for each declared workflow."""
    checks = []
    published = ["http-www", "http-api", "https-www", "https-api", "origin-nginx"]
    for application in manifest["applications"]:
        layers = [*published, *["native-" + str(port) for port in application["ports"]]]
        for layer in layers:
            found = [
                entry
                for entry in observations
                if entry.get("application") == application["id"]
                and entry.get("layer") == layer
            ]
            assertions = set().union(
                *(set(entry.get("assertions", [])) for entry in found)
            )
            missing = sorted(set(application["workflows"]) - assertions)
            checks.append(
                {
                    "application": application["id"],
                    "layer": layer,
                    "missing": missing,
                    "passed": not missing,
                }
            )
    return {
        "checks": checks,
        "complete": bool(checks) and all(check["passed"] for check in checks),
    }


BROWSER_KINDS = {
    "juice-shop": "juice",
    "csd-demo": "csd",
    "dvwa": "dvwa",
    "dvga": "dvga",
    "httpbin": "httpbin",
    "restaurant": "restaurant",
    "crapi": "crapi",
}


def http_observations(output: Path, fixture: Path, layers: list) -> list[dict]:
    """Read the installed HTTP slices from each native and published layer."""
    observations = []
    for layer, base in [("native", None), *layers]:
        receipt_path = output / (layer + "-http.json")
        command = [
            "/usr/local/bin/origin-verify-workflows",
            "--manifest",
            "/opt/origin-server/applications.json",
            "--fixtures",
            str(fixture),
            "--output",
            str(receipt_path),
        ]
        command.extend(["--native"] if base is None else ["--base", base])
        with (output / (layer + "-http.log")).open("w") as log:
            subprocess.run(  # noqa: S603 - exact installed verifier argv
                command, stdout=log, stderr=subprocess.STDOUT, check=False, timeout=600
            )
        receipt = json.loads(receipt_path.read_text())
        for check in receipt["checks"]:
            if check.get("passed"):
                native_layer = (
                    "native-" + check["layer"].rsplit(":", 1)[1]
                    if base is None
                    else layer
                )
                observations.append(
                    {
                        "application": check["application"],
                        "layer": native_layer,
                        "assertions": check.get("assertions", []),
                    }
                )
    return observations


def browser_observations(
    output: Path, manifest: dict, layers: list, provenance: dict
) -> list[dict]:
    """Run each declared browser kind on every native and published target."""
    observations = []
    for application in manifest["applications"]:
        kind = BROWSER_KINDS.get(application["id"])
        if kind is None:
            continue
        targets = [
            ("native-" + str(port), "http://127.0.0.1:" + str(port))
            for port in application["ports"]
        ]
        for layer, base in [*targets, *layers]:
            directory = output / (application["id"] + "-" + layer)
            command = [
                "/usr/local/bin/origin-browser-verify",
                kind,
                "--base",
                base,
                "--output",
                str(directory),
            ]
            if layer.startswith("native-") and kind in {
                "juice",
                "dvwa",
                "dvga",
                "httpbin",
                "csd",
            }:
                command.append("--native")
            with (output / (application["id"] + "-" + layer + ".log")).open("w") as log:
                subprocess.run(  # noqa: S603 - exact installed verifier argv
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=1000,
                )
            if (directory / "receipt.json").is_file():
                receipt = json.loads((directory / "receipt.json").read_text())
                runtime = json.loads((directory / "runtime-receipt.json").read_text())
                verifier = Path(
                    "/opt/origin-server/browser-runtime/verify_"
                    + ("juice" if kind == "juice" else kind)
                    + "_browser.mjs"
                )
                digest = hashlib.sha256(verifier.read_bytes()).hexdigest()
                assertions = (
                    browser_assertions(kind, receipt, runtime, provenance, base)
                    if runtime.get("verifier_sha256") == digest
                    else set()
                )
                observations.append(
                    {
                        "application": application["id"],
                        "layer": layer,
                        "assertions": sorted(assertions),
                    }
                )
            print(
                json.dumps(
                    {
                        "application": application["id"],
                        "layer": layer,
                        "browser_assertions": sorted(assertions)
                        if (directory / "receipt.json").is_file()
                        else [],
                    }
                ),
                flush=True,
            )
    return observations


def signup_observations(
    output: Path, manifest: dict, layers: list, provenance: dict
) -> list[dict]:
    """Signup is a separate stateful browser slice with mandatory recovery."""
    observations = []
    crapi = next(app for app in manifest["applications"] if app["id"] == "crapi")
    targets = [
        ("native-" + str(port), "http://127.0.0.1:" + str(port))
        for port in crapi["ports"]
    ]
    for layer, base in [*targets, *layers]:
        directory = output / ("crapi-signup-" + layer)
        command = [
            "/usr/local/bin/origin-browser-verify",
            "crapi-signup",
            "--base",
            base,
            "--output",
            str(directory),
        ]
        with (output / ("crapi-signup-" + layer + ".log")).open("w") as log:
            subprocess.run(  # noqa: S603 - installed scoped signup verifier
                command, stdout=log, stderr=subprocess.STDOUT, check=False, timeout=1000
            )
        if (directory / "receipt.json").exists():
            receipt = json.loads((directory / "receipt.json").read_text())
            runtime = json.loads((directory / "runtime-receipt.json").read_text())
            digest = hashlib.sha256(
                Path(
                    "/opt/origin-server/browser-runtime/verify_crapi_signup.mjs"
                ).read_bytes()
            ).hexdigest()
            assertions = (
                browser_assertions("crapi-signup", receipt, runtime, provenance, base)
                if runtime.get("verifier_sha256") == digest
                else set()
            )
            observations.append(
                {
                    "application": "crapi",
                    "layer": layer,
                    "assertions": sorted(assertions),
                }
            )
        print(json.dumps({"application": "crapi-signup", "layer": layer}), flush=True)
    return observations


def csd_replica_state(layers: list) -> list[dict]:
    """A tagged receiver mutation must be visible and removable on every serving layer."""
    marker = "replica-" + uuid.uuid4().hex
    targets = [
        ("native-" + str(port), "http://127.0.0.1:" + str(port), "")
        for port in range(5001, 5005)
    ]
    targets.extend((layer, base, "/csd-demo") for layer, base in layers)

    def request(
        base: str, prefix: str, path: str, body: dict | None = None
    ) -> dict | list:
        data = json.dumps(body).encode() if body is not None else None
        req = Request(  # noqa: S310 - explicit owned HTTP serving layers
            base + prefix + path,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Demo-Fixture": marker,
                "X-MUD-User": "benign-" + uuid.uuid4().hex,
            },
        )
        with urlopen(req, timeout=20) as response:  # noqa: S310 - owned serving-layer targets
            if response.status != HTTP_SUCCESS:
                message = "unexpected replica-state status"
                raise ValueError(message)
            return json.load(response)

    observed = []
    passed = False
    before = request("http://127.0.0.1:5001", "", "/exfil/log")
    try:
        result = request("http://127.0.0.1:5001", "", "/exfil", {"demo_id": marker})
        if not isinstance(result, dict) or result.get("status") != "received":
            message = "replica receiver failed"
            raise ValueError(message)
        for _, base, prefix in targets:
            entries = request(base, prefix, "/exfil/log")
            observed.append(
                any(
                    entry.get("fixture_id") == marker
                    and entry.get("payload", {}).get("demo_id") == marker
                    for entry in entries
                )
            )
    finally:
        cleared = request("http://127.0.0.1:5001", "", "/exfil/clear", {})
        after = request("http://127.0.0.1:5001", "", "/exfil/log")
        passed = (
            isinstance(cleared, dict)
            and cleared.get("status") == "cleared"
            and not any(entry.get("fixture_id") == marker for entry in after)
            and all(entry in after for entry in before)
        )
    if not passed or not all(observed) or len(observed) != len(targets):
        return []
    return [
        {"application": "csd-demo", "layer": layer, "assertions": ["replica-state"]}
        for layer, _, _ in targets
    ]


def main() -> int:
    """Run each serving layer and report missing declared workflow evidence."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domain", action="append", required=True)
    args = parser.parse_args()
    if len(args.domain) != DOMAIN_COUNT:
        parser.error("two published domains required")
    if any(not re.fullmatch(r"[a-z0-9.-]+", domain) for domain in args.domain):
        parser.error("DNS domain required")
    output = args.output
    if any(parent.is_symlink() for parent in (output, *output.parents)):
        parser.error("evidence path cannot traverse symlink")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    provenance = json.loads(Path("/opt/origin-server/install-receipt.json").read_text())
    manifest = json.loads(Path("/opt/origin-server/applications.json").read_text())
    fixture = output / "fixtures.json"
    result = subprocess.run(
        ["/usr/local/bin/demo-catalog-fixtures"],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    fixture.write_text(result.stdout)
    fixture.chmod(0o600)
    observations = []
    layers = [("origin-nginx", "http://127.0.0.1")]
    layers.extend(
        (protocol + "-" + label, protocol + "://" + domain)
        for protocol in ("http", "https")
        for label, domain in zip(("www", "api"), args.domain, strict=True)
    )
    observations.extend(http_observations(output, fixture, layers))
    observations.extend(csd_replica_state(layers))
    observations.extend(browser_observations(output, manifest, layers, provenance))
    observations.extend(signup_observations(output, manifest, layers, provenance))
    final_provenance = json.loads(
        Path("/opt/origin-server/install-receipt.json").read_text()
    )
    matrix = coverage_matrix(manifest, observations)
    matrix["source_stable"] = final_provenance == provenance
    matrix["complete"] &= matrix["source_stable"]
    matrix.update(
        source_commit=provenance["source_commit"],
        archive_sha256=provenance["archive_sha256"],
        completed=time.time(),
        screenshots_reviewed=False,
        accepted=False,
        observations=observations,
    )
    path = output / "matrix-receipt.json"
    path.write_text(json.dumps(matrix, indent=2))
    path.chmod(0o600)
    return int(not matrix["complete"])


if __name__ == "__main__":
    raise SystemExit(main())
