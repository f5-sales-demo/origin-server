"""Keep native GraphQL CPU work outside the gevent HTTP serving greenlet."""

import io
import subprocess
from importlib import import_module
from threading import current_thread, main_thread
from typing import Any


class NativeGraphQLThreadIsolation:
    """Execute complete native GraphQL responses in a bounded worker pool.

    Request input is read by the serving greenlet before dispatch. The worker
    owns application execution and iterator cleanup; status, headers and body
    bytes return unchanged to the serving greenlet. Other routes and upgrades
    retain their native streaming behavior.
    """

    def __init__(self, application: Any, pool: Any = None) -> None:
        """Use eight workers within the existing declared replica capacity."""
        if pool is None:
            pool = import_module("gevent.threadpool").ThreadPool(8)
        self.application = application
        self.pool = pool

    def __call__(self, environ: dict, start_response: Any) -> Any:
        """Return the native response after yielding the serving greenlet."""
        if environ.get("PATH_INFO") != "/graphql" or environ.get("HTTP_UPGRADE"):
            return self.application(environ, start_response)
        copied = dict(environ)
        length = int(environ.get("CONTENT_LENGTH") or 0)
        copied["wsgi.input"] = io.BytesIO(environ["wsgi.input"].read(length))
        copied["wsgi.multithread"] = True
        status, headers, chunks = self.pool.apply(lambda: self._execute(copied))
        start_response(status, headers, None)
        return chunks

    def _execute(self, environ: dict) -> tuple:
        response: dict = {}
        chunks: list[bytes] = []

        def capture(status: str, headers: list, exc_info: Any = None) -> Any:
            if exc_info is not None:
                try:
                    if chunks:
                        raise exc_info[1].with_traceback(exc_info[2])
                finally:
                    exc_info = None
            elif response:
                message = "Native WSGI response headers already supplied"
                raise AssertionError(message)
            response.update(status=status, headers=headers)
            return chunks.append

        iterator = self.application(environ, capture)
        try:
            chunks.extend(iterator)
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()
        return response["status"], response["headers"], chunks


def native_command_output(command: str) -> str:
    """Retain native shell output with the subprocess implementation for this thread.

    Gevent child watchers require the main loop. GraphQL workers can use native
    blocking subprocesses because they already run outside the HTTP greenlet.
    """
    runner = (
        import_module("gevent.subprocess")
        if current_thread() is main_thread()
        else subprocess
    )
    process = runner.Popen(  # noqa: S604 - preserve native commands in the authorized vulnerable demo
        command, shell=True, stdout=runner.PIPE, text=True
    )
    return process.communicate()[0]
