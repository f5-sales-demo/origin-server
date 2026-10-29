"""Preserve native WSGI responses while isolating GraphQL execution."""

import importlib.util
import io
import sys
import threading
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


class WorkerPool:
    def apply(self, function):
        result = []
        errors = []

        def execute():
            try:
                result.append(function())
            except Exception as error:  # pylint: disable=broad-exception-caught
                # Preserve native worker failures at the caller.
                errors.append(error)

        worker = threading.Thread(target=execute)
        worker.start()
        worker.join()
        if errors:
            raise errors[0]
        return result[0]


@pytest.fixture
def middleware():
    specification = importlib.util.spec_from_file_location(
        "dvga_wsgi", ROOT / "scripts/dvga_wsgi.py"
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.NativeGraphQLThreadIsolation


def request(path="/graphql", body=b"native query", **extra):
    return {
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        **extra,
    }


def test_response_bytes_headers_write_order_and_iterator_cleanup(middleware):
    serving_thread = threading.get_ident()
    events = []
    received = []
    writers: list[Any] = []
    environ = request()

    class Body:
        def __iter__(self):
            assert threading.get_ident() != serving_thread
            yield b"first"
            writers[0](b"second")
            yield b"third"

        def close(self):
            events.append(("close", threading.get_ident()))

    def application(copied, start_response):
        assert copied is not environ
        assert copied["wsgi.input"].read() == b"native query"
        assert threading.get_ident() != serving_thread
        write = start_response(
            "201 Created", [("X-Native", "exact"), ("X-Native", "two")]
        )
        writers.append(write)
        write(b"prefix")
        return Body()

    def start_response(status, headers, exc_info=None):
        assert threading.get_ident() == serving_thread
        received.append((status, headers, exc_info))

    response = middleware(application, pool=WorkerPool())(environ, start_response)
    assert list(response) == [b"prefix", b"first", b"second", b"third"]
    assert received == [
        ("201 Created", [("X-Native", "exact"), ("X-Native", "two")], None)
    ]
    assert events == [("close", events[0][1])]
    assert events[0][1] != serving_thread


@pytest.mark.parametrize(
    ("path", "upgrade"),
    [("/", ""), ("/static/native.css", ""), ("/graphql", "websocket")],
)
def test_non_graphql_and_upgrades_keep_native_streaming(middleware, path, upgrade):
    environ = request(path, HTTP_UPGRADE=upgrade)
    native_body = iter([b"native"])

    def application(actual, start_response):
        assert actual is environ
        start_response("200 OK", [])
        return native_body

    assert (
        middleware(application, pool=WorkerPool())(environ, lambda *_: None)
        is native_body
    )
    assert environ["wsgi.input"].tell() == 0


def test_native_failure_propagates_and_closes_iterator(middleware):
    closed = []

    class Body:
        def __iter__(self):
            yield b"first"
            message = "native failure"
            raise RuntimeError(message)

        def close(self):
            closed.append(True)

    def application(environ, start_response):
        start_response("200 OK", [])
        return Body()

    with pytest.raises(RuntimeError, match="native failure"):
        middleware(application, pool=WorkerPool())(request(), lambda *_: None)
    assert closed == [True]


def test_native_error_response_and_empty_body_are_unchanged(middleware):
    received = []

    def application(environ, start_response):
        start_response("400 Bad Request", [("Content-Length", "0")])
        return []

    assert not (
        list(
            middleware(application, pool=WorkerPool())(
                request(body=b""), lambda *args: received.append(args)
            )
        )
    )
    assert received == [("400 Bad Request", [("Content-Length", "0")], None)]


def test_adapter_declares_runtime_module_in_rendered_image():
    sys.path.insert(0, str(ROOT / "scripts"))
    render = import_module("render_origin").render

    files = {entry["path"]: entry["content"] for entry in render(ROOT)}
    assert (
        files["/opt/origin-server/dvga-adapter/dvga_wsgi.py"]
        == (ROOT / "scripts/dvga_wsgi.py").read_text()
    )
    assert (
        "COPY dvga_wsgi.py /opt/dvga/dvga_wsgi.py"
        in files["/opt/origin-server/dvga-adapter/Dockerfile"]
    )
    assert (
        "NativeGraphQLThreadIsolation(app.wsgi_app)"
        in files["/opt/origin-server/dvga-adapter/adapt.py"]
    )


def test_native_command_keeps_exact_output_in_graphql_worker(middleware):
    module = import_module("dvga_wsgi")

    def application(environ, start_response):
        output = module.native_command_output("printf synthetic")
        start_response("200 OK", [])
        return [output.encode()]

    assert middleware(application, pool=WorkerPool())(request(), lambda *_: None) == [
        b"synthetic"
    ]
