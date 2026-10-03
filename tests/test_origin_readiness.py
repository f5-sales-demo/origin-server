"""Template/guest failure-path tests only; these are not live security acceptance."""

import ast
import concurrent.futures
import contextlib
import gzip
import io
import json
import re
import shlex
import subprocess
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from email.message import Message
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs
from urllib.response import addinfourl

import yaml
from origin_test_support import ensure, ensure_equal, expect_error

PROVISIONING = Path(__file__).resolve().parents[1] / "provisioning/files.json"


def embedded_files() -> dict[str, str]:
    """Read the authoritative shared provisioning source."""
    return {
        item["path"]: item["content"] for item in json.loads(PROVISIONING.read_text())
    }


# Dynamic module fixture has only the single attribute-resolution protocol.
class GuestModule(types.ModuleType):  # pylint: disable=too-few-public-methods
    """Expose dynamically executed guest globals without static member assumptions."""

    def __getattr__(self, name: str) -> Any:
        """Read a guest global by name.

        Args:
            name: Dynamic guest global identifier.

        Returns:
            Runtime value from the trusted guest namespace.
        """
        return self.__dict__[name]


def guest() -> Any:
    """Load only the trusted readiness script embedded in this repository.

    Returns:
        Isolated dynamic guest module used by synthetic fixture transports.
    """
    module = GuestModule("origin_guest")
    namespace: dict[str, Any] = module.__dict__
    # Audited execution: source is extracted solely from the owned repository YAML.
    exec(  # noqa: S102  # pylint: disable=exec-used
        compile(embedded_files()["/usr/local/bin/demo-origin-ready"], "guest", "exec"),
        namespace,
    )  # pylint: disable=exec-used
    return cast("Any", module)


class FixtureResponse(addinfourl):
    """Provide urllib's runtime response message attribute on a synthetic stream."""

    msg = "OK"


class OriginTests(unittest.TestCase):
    """Verify origin guest contracts without reaching deployed applications."""

    def test_csd_readiness_restores_its_own_receiver_fixture(self) -> None:
        g = guest()
        calls = []

        def request(port, path, data=None, **kwargs):
            calls.append((port, path, data, kwargs))
            if path == "/":
                return "checkout.js"
            if path == "/checkout.js":
                return "function updateCount() {}"
            if path == "/exfil":
                return '{"status":"received"}'
            if path == "/exfil/clear":
                return '{"status":"cleared"}'
            return "[]"

        with patch.object(g, "http", side_effect=request):
            g.replica("csd-demo", 5001)
        ensure(any(call[1] == "/exfil/clear" for call in calls))
        mutations = [call for call in calls if call[1] in ("/exfil", "/exfil/clear")]
        ensure_equal(len(mutations), 2)
        ensure(mutations[0][3]["fixture"] == mutations[1][3]["fixture"])

    def test_juice_directory_listings_use_final_body_framing(self) -> None:
        """Verify final response framing survives source adaptation."""
        files = embedded_files()
        source = files["/opt/origin-server/juice-shop-framing/preload.cjs"]
        ensure("serve-index" in source)
        ensure("removeHeader('Content-Length')" in source)
        ensure_equal(
            embedded_files()["/opt/origin-server/docker-compose.yml"].count(
                "NODE_OPTIONS=--require=/juice-shop/waap-framing.cjs"
            ),
            4,
        )

    def test_dvga_recovery_is_bounded_to_owned_replica_names(self) -> None:
        """Verify recovery touches only declared synthetic replicas."""
        files = embedded_files()
        source = files["/usr/local/bin/demo-dvga-recovery"]
        ensure("range(1, 5)" in source)
        ensure("container_name" in source)
        ensure("040aa33c199d99f" in source)
        compile(source, "recovery", "exec")

    def test_extract_compile_and_empty_terraform_variables(self) -> None:
        """Check the named origin guest regression contract."""
        text = PROVISIONING.read_text()
        ensure("cdn_simulator_host" not in text)
        ensure("origin-server" in text)
        ensure(len(gzip.compress(text.encode())) < 65536)
        for path, source in embedded_files().items():
            if source.startswith("#!/usr/bin/env python3"):
                compile(source, path, "exec")
            if source.startswith(("#!/bin/sh", "#!/bin/bash")):
                result = subprocess.run(
                    ["/bin/bash", "-n"],
                    input=source.replace("$${", "${"),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                ensure(result.returncode == 0, path + result.stderr)

    def test_pinned_images_and_all_replicas(self) -> None:
        """Check the named origin guest regression contract."""
        compose = embedded_files()["/opt/origin-server/docker-compose.yml"]
        for image in re.findall(r"^    image: (.+)$", compose, re.MULTILINE):
            ensure(re.search(r"@sha256:[0-9a-f]{64}$", image) is not None)
        g = guest()
        expected = {
            "juice-shop": 3001,
            "dvwa": 8101,
            "vampi": 5101,
            "httpbin": 8201,
            "whoami": 8082,
            "csd-demo": 5001,
            "dvga": 5201,
            "restaurant": 8301,
        }
        ensure_equal(g.FAMILIES, expected)
        for family, start in expected.items():
            for index in range(1, 5):
                ensure(family + "-" + str(index) + ":" in compose)
                ensure("127.0.0.1:" + str(start + index - 1) + ":" in compose)
        ensure("127.0.0.1:18888:80" in compose)
        ensure_equal(len(yaml.safe_load(compose)["services"]), 42)

    def test_every_compose_container_has_fail_closed_readiness(self) -> None:
        """Check the named origin guest regression contract."""
        g = guest()
        names = set(
            yaml.safe_load(embedded_files()["/opt/origin-server/docker-compose.yml"])[
                "services"
            ]
        )
        for failed in names:
            with self.subTest(container=failed):

                def inspect(name: str, *_args: object, failed: str = failed) -> None:
                    """Reject exactly the selected synthetic container."""
                    if name == failed:
                        message = "container unavailable"
                        raise ValueError(message)

                with (
                    patch.object(g, "container", side_effect=inspect) as containers,
                    patch.object(g, "replica"),
                    patch.object(g, "crapi_functional"),
                    patch.object(g, "command", return_value="1"),
                ):
                    result = g.check()
                ensure_equal(
                    {call.args[0] for call in containers.call_args_list}, names
                )
                ensure_equal(len(result["checks"]), 48)
                ensure(not result["ready"])
                ensure_equal(
                    [c["name"] for c in result["checks"] if not c["ready"]], [failed]
                )

    def test_http_response_and_deadline_are_bounded(self) -> None:
        """Check the named origin guest regression contract."""
        g = guest()
        g.__dict__["DEADLINE"] = 12
        response = MagicMock()
        response.status = 200
        response.read.return_value = b"x" * (1024 * 1024 + 1)
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        with (
            patch.object(g.time, "monotonic", return_value=10),
            expect_error(ValueError, "oversized response"),
        ):
            g.http(18888, "/community/api/v2/community/posts/recent", opener=opener)
        ensure_equal(opener.open.call_args.kwargs["timeout"], 2)
        response.read.assert_called_once_with(1024 * 1024 + 1)
        with (
            patch.object(g.time, "monotonic", return_value=12),
            expect_error(TimeoutError),
        ):
            g.command("docker", "inspect", "restaurant-1")

    def test_missing_tools_or_container_never_ready(self) -> None:
        """Check the named origin guest regression contract."""
        g = guest()
        with (
            patch.object(g, "command", side_effect=FileNotFoundError),
            patch.object(g, "http", side_effect=OSError),
        ):
            result = g.check()
        ensure(not result["ready"])
        ensure_equal(len(result["checks"]), 48)
        ensure(bool(all(not check["ready"] for check in result["checks"])))

    def test_each_replica_failure_is_preserved(self) -> None:
        """Check the named origin guest regression contract."""
        g = guest()
        for family in g.FAMILIES:
            with self.subTest(family=family):

                def replica(name: str, _port: int, family: str = family) -> None:
                    """Reject every replica in the selected family."""
                    if name == family:
                        message = "unavailable"
                        raise ValueError(message)

                with (
                    patch.object(g, "container"),
                    patch.object(g, "command", return_value="1"),
                    patch.object(g, "replica", side_effect=replica),
                    patch.object(g, "crapi_functional"),
                ):
                    result = g.check()
                ensure(not result["ready"])
                failures = [c["name"] for c in result["checks"] if not c["ready"]]
                ensure_equal(failures, [family + "-" + str(i) for i in range(1, 5)])

    @staticmethod
    def initializer_transport(
        failures: dict[tuple[str, str], list[int | Exception]] | None = None,
        setup: str | None = None,
        post_body: bytes = b"<em>Setup successful</em>!",
    ) -> tuple[
        Any,
        list[urllib.request.Request],
        list[urllib.request.Request],
        contextlib.ExitStack,
    ]:
        """Build a cookie-aware synthetic initializer transport.

        Args:
            failures: Ordered status or transport failures by method and path.
            setup: Optional synthetic setup form.
            post_body: Synthetic successful database reset response.

        Returns:
            Guest module, observed requests, posted requests, and patch context.
        """
        g = guest()
        seen: list[urllib.request.Request] = []
        posted: list[urllib.request.Request] = []
        queued_failures = dict(failures or {})
        if any(path == "/createdb" for _, path in queued_failures):
            queued_failures[("GET", "/users/v1")] = [500]
        g.__dict__["DEADLINE"] = time.monotonic() + 2
        setup = (
            setup
            if setup is not None
            else (
                "<form method='post' action='#'>"
                "<input name='create_db'><input name='user_token' value='abc123'></form>"
            )
        )

        class Transport(urllib.request.HTTPHandler):
            """Serve fixture bodies through urllib's real cookie processor."""

            def http_open(self, req: urllib.request.Request) -> Any:
                """Return the requested synthetic initializer response."""
                seen.append(req)
                path = urllib.parse.urlparse(req.full_url).path
                headers = Message()
                key = (req.get_method(), path)
                if queued_failures.get(key):
                    code = queued_failures[key].pop(0)
                    if isinstance(code, Exception):
                        raise code
                    raise urllib.error.HTTPError(
                        req.full_url, code, "private token body", headers, None
                    )
                if req.get_method() == "POST":
                    ensure_equal(req.get_header("Cookie"), "PHPSESSID=synthetic")
                    ensure_equal(
                        req.get_header("Content-type"),
                        "application/x-www-form-urlencoded",
                    )
                    ensure_equal(
                        parse_qs(cast("bytes", req.data).decode()),
                        {
                            "create_db": ["Create / Reset Database"],
                            "user_token": ["abc123"],
                        },
                    )
                    posted.append(req)
                    body = post_body
                elif path == "/setup.php":
                    headers["Set-Cookie"] = "PHPSESSID=synthetic; Path=/"
                    body = cast("str", setup).encode()
                elif path == "/login.php":
                    body = b"Login user_token"
                elif path == "/":
                    body = b'{"message":"VAmPI the Vulnerable API"}'
                elif path == "/users/v1":
                    body = b'{"users":[{"username":"synthetic"}]}'
                else:
                    body = b'{"message":"Database populated."}'
                response = FixtureResponse(io.BytesIO(body), headers, req.full_url, 200)
                response.msg = "OK"
                return response

        def command(*args: str) -> str:
            """Return fixture database counts without invoking Docker."""
            if "information_schema.tables" in args[-1]:
                return "1" if posted else "0"
            if args[-1] == "SELECT COUNT(*) FROM users":
                return "5"
            return "1"

        real_builder = urllib.request.build_opener
        stack = contextlib.ExitStack()
        stack.enter_context(
            patch.object(
                g.urllib.request,
                "build_opener",
                side_effect=lambda *handlers: real_builder(*handlers, Transport()),
            )
        )
        stack.enter_context(patch.object(g, "container"))
        stack.enter_context(patch.object(g, "command", side_effect=command))
        return g, seen, posted, stack

    def test_initializer_executes_real_cookie_and_form_flow(self) -> None:
        """Check the named origin guest regression contract."""
        g, seen, posted, stack = self.initializer_transport()
        with stack:
            g.initialize()
        ensure_equal(len(posted), 1)
        ensure_equal(
            [r.full_url for r in seen if r.full_url.endswith("/createdb")],
            [],
        )
        ensure_equal(sum(r.full_url.endswith("/users/v1") for r in seen), 8)

    def test_initializer_retries_only_pre_mutation_503_and_429(self) -> None:
        """Check the named origin guest regression contract."""
        g, _seen, posted, stack = self.initializer_transport(
            {("GET", "/setup.php"): [503, 429], ("GET", "/"): [503]}
        )
        with stack, patch.object(g.time, "sleep") as sleep:
            g.initialize()
        ensure_equal(len(posted), 1)
        ensure_equal(sleep.call_count, 3)

    def test_initializer_rejects_non_form_or_missing_token(self) -> None:
        """Check the named origin guest regression contract."""
        for setup in [
            "<input name='user_token' value='abc123'>",
            "<form method='post'><input name='create_db'></form>",
        ]:
            g, _seen, posted, stack = self.initializer_transport(setup=setup)
            with stack, expect_error(g.PhaseError) as raised:
                g.initialize()
            ensure_equal(cast("Any", raised.exception).phase, "dvwa-1:setup-get")
            ensure(not posted)

    def test_mutation_http_errors_are_labeled_fatal_and_not_retried(self) -> None:
        """Check the named origin guest regression contract."""
        for method, path, phase in [
            ("POST", "/setup.php", "dvwa-1:setup-post"),
            ("GET", "/createdb", "vampi-1:createdb-get"),
        ]:
            for code in (400, 500, 503):
                g, seen, _posted, stack = self.initializer_transport(
                    {(method, path): [code]}
                )
                output = io.StringIO()
                with (
                    stack,
                    patch("sys.argv", ["ready", "--initialize"]),
                    contextlib.redirect_stdout(output),
                ):
                    ensure_equal(g.main(), 1)
                report = json.loads(output.getvalue())
                ensure_equal(report["phase"], phase)
                ensure_equal(report["http_status"], code)
                ensure_equal(report["error"], "HTTPError")
                ensure("private" not in output.getvalue())
                ensure_equal(
                    sum(
                        r.get_method() == method and r.full_url.endswith(path)
                        for r in seen
                    ),
                    1,
                )

    def test_setup_400_and_200_csrf_failure_never_become_ready(self) -> None:
        """Check the named origin guest regression contract."""
        cases: list[dict[str, Any]] = [
            {"failures": {("GET", "/setup.php"): [400]}},
            {"post_body": b"CSRF token is incorrect"},
        ]
        for kwargs in cases:
            g, seen, _posted, stack = self.initializer_transport(**kwargs)
            with stack, expect_error(g.PhaseError) as raised:
                g.initialize()
            ensure(
                cast("Any", raised.exception).phase
                in ("dvwa-1:setup-get", "dvwa-1:setup-post")
            )
            ensure(not any(r.full_url.endswith("/createdb") for r in seen))

    def test_transport_deadline_failure_is_safe_and_phase_specific(self) -> None:
        """Check the named origin guest regression contract."""
        g, _seen, posted, stack = self.initializer_transport(
            {("GET", "/setup.php"): [urllib.error.URLError("secret DNS host")] * 5}
        )
        g.__dict__["DEADLINE"] = 1
        clock = [0.0]

        def sleep(seconds: float) -> None:
            """Advance only the synthetic deadline clock."""
            clock[0] += seconds

        with (
            stack,
            patch.object(g.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(g.time, "sleep", side_effect=sleep),
            expect_error(g.PhaseError) as raised,
        ):
            g.initialize()
        ensure_equal(cast("Any", raised.exception).phase, "dvwa-1:setup-get")
        ensure_equal(clock[0], 1)
        ensure(not posted)
        ensure("secret" not in json.dumps(g.diagnostic(raised.exception)))

    def test_concurrent_cookie_jars_never_cross_sessions(self) -> None:
        """Check the named origin guest regression contract."""
        barrier = threading.Barrier(2)

        class Transport(urllib.request.HTTPHandler):
            """Maintain one synthetic session per independent cookie jar."""

            def __init__(self, session: str) -> None:
                """Bind the transport to one synthetic session."""
                super().__init__()
                self.session = session

            def http_open(self, req: urllib.request.Request) -> Any:
                """Serve synchronized fixture responses without networking."""
                headers = Message()
                if req.data is None:
                    headers["Set-Cookie"] = "PHPSESSID=" + self.session + "; Path=/"
                    body = self.session.encode()
                    barrier.wait(timeout=5)
                else:
                    ensure_equal(req.get_header("Cookie"), "PHPSESSID=" + self.session)
                    ensure_equal(cast("bytes", req.data).decode(), self.session)
                    body = b"ok"
                response = FixtureResponse(io.BytesIO(body), headers, req.full_url, 200)
                response.msg = "OK"
                return response

        def session_flow(session: str) -> str:
            """Exercise the guest HTTP helper with an independent cookie jar."""
            g = guest()
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(CookieJar()), Transport(session)
            )
            token = g.http(8101, "/setup.php", opener=opener)
            return g.http(8101, "/setup.php", data=token.encode(), opener=opener)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(session_flow, session) for session in ("a1", "b2")]
            ensure_equal(
                [future.result(timeout=10) for future in futures], ["ok", "ok"]
            )

    def test_verified_dvwa_seed_skips_reset_but_all_vampi_replicas_initialize(
        self,
    ) -> None:
        """Check the named origin guest regression contract."""
        g, seen, posted, stack = self.initializer_transport()
        with stack, patch.object(g, "dvwa_seeded", return_value=True):
            g.initialize()
        ensure(not posted)
        ensure_equal(sum(r.full_url.endswith("/setup.php") for r in seen), 4)
        ensure_equal(sum(r.full_url.endswith("/createdb") for r in seen), 0)


class OriginRuntimeTests(unittest.TestCase):
    """Check pinned runtime layout, readiness failures, and provisioner sequencing."""

    def test_stale_or_missing_database_is_fatal(self) -> None:
        """Check the named origin guest regression contract."""
        g = guest()
        with (
            patch.object(g, "container"),
            patch.object(g, "replica"),
            patch.object(g, "crapi_functional"),
            patch.object(g, "command", return_value="0"),
        ):
            result = g.check()
        ensure(not result["ready"])
        ensure_equal(
            [c["name"] for c in result["checks"] if not c["ready"]],
            ["dvwa-database", "restaurant-database", "crapi-database"],
        )

    def test_static_health_cannot_substitute_for_functional_response(self) -> None:
        """Check the named origin guest regression contract."""
        g = guest()
        for family, port in g.FAMILIES.items():
            with (
                self.subTest(family=family),
                patch.object(g, "http", return_value='{"status":"healthy"}'),
                expect_error((ValueError, KeyError, TypeError, AttributeError)),
            ):
                g.replica(family, port)
        with (
            patch.object(g, "http", return_value="<html>healthy</html>"),
            expect_error(ValueError),
        ):
            g.crapi_functional()

    def test_unhealthy_and_restarting_containers_fail(self) -> None:
        """Check the named origin guest regression contract."""
        g = guest()
        for state in [
            {"Running": False},
            {"Running": True, "Restarting": True},
            {"Running": True, "Health": {"Status": "starting"}},
        ]:
            with (
                patch.object(g, "command", return_value=json.dumps(state)),
                expect_error(ValueError),
            ):
                g.container("crapi-identity", health=True)

    def test_timeout_is_nonzero_machine_readable_and_redacted(self) -> None:
        """Check the named origin guest regression contract."""
        g = guest()
        output = io.StringIO()
        with (
            patch("sys.argv", ["demo-origin-ready", "--timeout-seconds", "1"]),
            patch.object(g.time, "monotonic", side_effect=[0, 2]),
            patch.object(g, "check", return_value={"ready": False, "checks": []}),
            contextlib.redirect_stdout(output),
        ):
            ensure_equal(g.main(), 1)
        ensure(not json.loads(output.getvalue())["ready"])

    def test_pinned_runtime_layout_and_wsgi_entrypoint(self) -> None:
        """Check the named origin guest regression contract."""
        files = embedded_files()
        compose = files["/opt/origin-server/docker-compose.yml"]
        services = yaml.safe_load(compose)["services"]
        for index in range(1, 5):
            service = services[f"restaurant-{index}"]
            ensure_equal(service["working_dir"], "/app")
            ensure_equal(service["command"][:2], ["uvicorn", "main:app"])
        argv = shlex.split(
            next(
                line
                for line in files["/opt/origin-server/vampi-gunicorn.sh"].splitlines()
                if line.startswith("exec gunicorn")
            )
        )
        module, export = argv[argv.index("0.0.0.0:5000") + 1].split(":")
        ensure_equal(module, "config")
        ensure(isinstance(ast.parse(export, mode="eval").body, ast.Name))
        # Exact pinned image config.py exports the framework's App; 2.14.2 AbstractApp.__call__
        # delegates to self.app(environ, start_response). Attribute syntax is rejected by Gunicorn.
        pinned_export = ast.parse(
            "vuln_app = connexion.App(__name__, specification_dir='./openapi_specs')"  # codespell:ignore connexion
        )
        ensure_equal(
            export,
            cast("ast.Name", cast("ast.Assign", pinned_export.body[0]).targets[0]).id,
        )
        ensure_equal(
            cast(
                "ast.Attribute",
                cast("ast.Call", cast("ast.Assign", pinned_export.body[0]).value).func,
            ).attr,
            "App",
        )
        ensure(
            "import_app('config:vuln_app')"
            in files["/opt/origin-server/vampi/Dockerfile"]
        )
        ensure("pip install" not in files["/opt/origin-server/vampi-gunicorn.sh"])
        ensure("--require-hashes" in files["/opt/origin-server/csd-demo/Dockerfile"])
        ensure(
            "https://" not in files["/opt/origin-server/csd-demo/templates/checkout.js"]
        )
        for key, source in files.items():
            if key.endswith("Dockerfile"):
                for image in re.findall(r"^FROM (\S+)", source, re.MULTILINE):
                    ensure(re.search(r"@sha256:[0-9a-f]{64}$", image) is not None)

    def test_gevent_runtime_dependencies_are_complete(self) -> None:
        """Check the named origin guest regression contract."""
        files = embedded_files()
        requirements = files["/opt/origin-server/csd-demo/requirements.txt"]
        # Gunicorn 26.2.0 PyPI metadata declares packaging in its gevent extra.
        ensure("gunicorn[gevent]==26.2.0" in requirements)
        ensure("gevent==26.9.0" in requirements)
        ensure(
            (
                "packaging==26.0 --hash=sha256:"
                "b36f1fef9334a5588b4166f8bcd26a14e521f2b55e6b9de3aaa80d3ff7a37529"
            )
            in requirements
        )
        ensure(
            "import gunicorn.workers.ggevent"
            in files["/opt/origin-server/csd-demo/Dockerfile"]
        )
        ensure(
            "import_app('app:app')" in files["/opt/origin-server/csd-demo/Dockerfile"]
        )
        for line in requirements.splitlines():
            if line and not line.startswith("#"):
                ensure(
                    re.search(r"^[\w.\[\]-]+==[\d.]+ --hash=sha256:[0-9a-f]{64}$", line)
                    is not None
                )
        packages = json.loads((PROVISIONING.parent / "packages.json").read_text())
        ensure("dool" not in packages)
        ensure("sysstat" in packages)
        ensure("iotop" in packages)

    def test_required_provisioning_failure_stops_execution(self) -> None:
        """Check the named origin guest regression contract."""
        provision = embedded_files()["/usr/local/bin/demo-origin-provision"]
        ensure("set -Eeuo pipefail" in provision)
        ensure("timeout 1200 docker compose build" in provision)
        ensure("--initialize --timeout-seconds 300" in provision)
        compose = embedded_files()["/opt/origin-server/docker-compose.yml"]
        ensure("alembic upgrade head" not in compose)
        ensure_equal(provision.count("alembic upgrade head"), 1)
        # Run the actual guest provisioner; intercept first host operations to avoid mutations.
        shell = provision.replace(
            ". /usr/local/lib/cloud-init-helpers.sh",
            'log_phase() { printf "%s\\n" "$*"; }; '
            "sed() { return 0; }; systemctl() { return 17; }",
        )
        # Audited repository provisioner: host operations replaced with inert functions.
        result = subprocess.run(  # noqa: S603
            ["/bin/bash", "-c", shell], capture_output=True, text=True, check=False
        )
        ensure_equal(result.returncode, 17)
        ensure("failed origin provisioning aborted" in result.stdout)
        ensure(
            "all origin replicas and functional dependencies verified"
            not in result.stdout
        )

    def test_nginx_activation_precedes_fallible_initialization(self) -> None:
        """Check the named origin guest regression contract."""
        provision = embedded_files()["/usr/local/bin/demo-origin-provision"]
        # Execute the recorded activation and readiness phases without touching the host.
        activation = provision[
            provision.index(
                "ln -sf /etc/nginx/sites-available/origin-server"
            ) : provision.index("# GitHub commits/main receipt")
        ]
        readiness = provision[
            provision.index("/usr/local/bin/demo-origin-ready --initialize") :
        ]
        shell = (
            "set -Eeuo pipefail\n"
            + activation
            + readiness.replace("/usr/local/bin/demo-origin-ready", "demo_origin_ready")
        )
        receiver = r"""
        site_enabled=0; default_removed=0; loaded_site=default
        ln() { site_enabled=1; printf '%s\n' "site-enabled"; }
        rm() { default_removed=1; printf '%s\n' "default-removed"; }
        nginx() {
          [ "$*" = '-t' ] || return 19
          [ "$site_enabled $default_removed" = '1 1' ] || return 20
          printf '%s\n' "nginx-test"
          return "$validation_status"
        }
        systemctl() {
          printf '%s\n' "systemctl $*"
          case "$*" in
            'enable nginx') ;;
            'restart nginx') loaded_site=origin ;;
            *) return 21 ;;
          esac
        }
        demo_origin_ready() {
          printf '%s\n' "readiness $* loaded=$loaded_site"
          [ "$loaded_site" = origin ] || return 22
          return 23
        }
        log_phase() { printf '%s\n' "phase $*"; }
        """
        for validation_status, expected_status, expected in [
            (
                0,
                23,
                [
                    "site-enabled",
                    "default-removed",
                    "nginx-test",
                    "systemctl enable nginx",
                    "systemctl restart nginx",
                    "readiness --initialize --timeout-seconds 300 loaded=origin",
                ],
            ),
            (17, 17, ["site-enabled", "default-removed", "nginx-test"]),
        ]:
            with self.subTest(validation_status=validation_status):
                # Audited repository shell fragments use inert activation receivers.
                result = subprocess.run(  # noqa: S603
                    [
                        "/bin/bash",
                        "-c",
                        f"validation_status={validation_status}\n" + receiver + shell,
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                ensure(result.returncode == expected_status, result.stderr)
                ensure_equal(result.stdout.splitlines(), expected)
        ensure_equal(provision.count("systemctl restart nginx"), 1)

    def test_serialized_migration_uses_runtime_workdir(self) -> None:
        """Check the named origin guest regression contract."""
        source = embedded_files()["/usr/local/bin/demo-origin-provision"]
        migration = next(
            line for line in source.splitlines() if "alembic upgrade head" in line
        )
        # Execute the real migration invocation with a non-mutating argv receiver.
        receiver = """
        set -eu
        timeout() { shift; "$@"; }
        docker() {
          [ "$1 $2 $3 $4 $5 $6 $7" = "compose run --rm --no-deps --workdir /app restaurant-1" ] || return 19
          shift 7
          [ "$1 $2" = "sh -euc" ] || return 20
          [ "$3" = 'alembic upgrade head; python -c "import main"' ] || return 21
          echo serialized-migration
        }
        """
        # Audited repository migration invocation uses a non-mutating argv receiver.
        result = subprocess.run(  # noqa: S603
            ["/bin/sh", "-c", receiver + migration],
            text=True,
            capture_output=True,
            check=False,
        )
        ensure(result.returncode == 0, result.stderr)
        ensure("serialized-migration" in result.stdout)

    def test_crapi_paginated_posts_contract(self) -> None:
        """Check the named origin guest regression contract."""
        g = guest()
        # Synthetic contract fixtures, not claims of observed live crAPI responses.
        valid = {
            "posts": [
                {"id": "seed-id", "title": "seed-title", "content": "seed-content"}
            ],
            "total": 1,
            "next_offset": None,
            "previous_offset": None,
        }
        invalid = [
            valid["posts"],
            {},
            {**valid, "posts": []},
            {**valid, "posts": ["healthy"]},
            {**valid, "posts": [{}]},
            {**valid, "total": True},
            {**valid, "total": 2},
            {**valid, "next_offset": "1"},
            {**valid, "previous_offset": -1},
        ]

        def responses(page: object) -> list[str]:
            """Return synthetic crAPI endpoint bodies with the supplied page."""
            return [
                "<html>crAPI</html>",
                '{"token":"synthetic"}',
                json.dumps(page),
                '{"initialized":"false"}',
                '{"products":[{"id":1}],"credit":100}',
                '{"items":[]}',
            ]

        with patch.object(g, "http", side_effect=responses(valid)) as http:
            g.crapi_functional()
            ensure_equal(
                http.call_args_list[2].args[1],
                "/community/api/v2/community/posts/recent?limit=1&offset=0",
            )
        for page in invalid:
            with (
                self.subTest(page=page),
                patch.object(g, "http", side_effect=responses(page)),
                expect_error(ValueError),
            ):
                g.crapi_functional()


if __name__ == "__main__":
    unittest.main()
