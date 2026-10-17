#!/usr/bin/env python3
"""Serve synthetic HTTP, TCP, and authenticated certificate diagnostics on Azure."""

from __future__ import annotations

import hashlib
import http.server
import json
import logging
import os
import socketserver
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from email.message import Message
    from typing import IO, Any

LIMIT = 1024 * 1024
MAX_CHALLENGE = 256
BIND = "0.0.0.0"  # noqa: S104 -- Explicit public synthetic origin listeners, controlled by Terraform NSG.


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward a managed identity token to a redirected endpoint."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        """Reject redirects before forwarding credentials."""
        message = "Certificate material endpoint redirected"
        raise ValueError(message)


def read_json(request: urllib.request.Request) -> dict[str, Any]:
    """Read bounded JSON without including response contents in errors."""
    with urllib.request.build_opener(
        NoRedirects(), urllib.request.ProxyHandler({})
    ).open(request, timeout=20) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        message = "Certificate material exceeds limit"
        raise ValueError(message)
    return json.loads(data)


def vault_material(vault: str, secret: str) -> dict[str, str]:
    """Retrieve private material using this VM's managed identity."""
    parsed = urllib.parse.urlsplit(vault)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".vault.azure.net")
        or parsed.path not in ("", "/")
        or any((parsed.query, parsed.fragment, parsed.username, parsed.password))
    ):
        message = "Expected an Azure Key Vault HTTPS origin"
        raise ValueError(message)
    if not secret or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
        for c in secret
    ):
        message = "Invalid material secret name"
        raise ValueError(message)
    identity = read_json(
        urllib.request.Request(
            "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fvault.azure.net",
            headers={"Metadata": "true"},
        )
    )
    material = read_json(
        urllib.request.Request(  # noqa: S310 -- Validated HTTPS Azure vault origin; redirects and proxies rejected.
            vault.rstrip("/") + "/secrets/" + secret + "?api-version=7.4",
            headers={"Authorization": "Bearer " + identity["access_token"]},
        )
    )
    return json.loads(material["value"])


class ConnectionFingerprint(Protocol):
    """Public serving fingerprint attached to an exact TLS connection."""

    origin_fingerprint: str


def tls_context(material: dict[str, str]) -> tuple[ssl.SSLContext, str]:
    """Load TLS keys through an anonymous memory file; never write them to disk."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.options |= ssl.OP_NO_TICKET
    context.num_tickets = 0
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cadata=material["client_ca"])
    if sys.platform != "linux":
        message = "Anonymous TLS key files require Linux"
        raise RuntimeError(message)
    descriptor = os.memfd_create("origin-tls", os.MFD_CLOEXEC)
    try:
        payload = (material["certificate"] + "\n" + material["private_key"]).encode()
        with os.fdopen(os.dup(descriptor), "wb") as stream:
            stream.write(payload)
        context.load_cert_chain("/proc/self/fd/" + str(descriptor))
    finally:
        os.close(descriptor)
    leaf = ssl.PEM_cert_to_DER_cert(
        material["certificate"].split("-----END CERTIFICATE-----", 1)[0]
        + "-----END CERTIFICATE-----"
    )
    return context, hashlib.sha256(leaf).hexdigest()


class Material:
    """Atomically replace serving contexts after a successful material refresh."""

    def __init__(self, loader: Callable[[], dict[str, str]]) -> None:
        """Retain only a validated serving context and its public fingerprint."""
        self.loader = loader
        self.current: tuple[ssl.SSLContext, str] | None = None

    def refresh(self) -> None:
        """Keep the previous healthy context when retrieval or validation fails."""
        prepared = tls_context(self.loader())
        self.current = prepared


class DiagnosticHTTPServer(http.server.ThreadingHTTPServer):
    """Declare the public encrypted-material path for diagnostic handlers."""

    material_file: str = ""


class Handler(http.server.BaseHTTPRequestHandler):
    """Report actual authenticated peer identity, never request-header identity."""

    def log_message(self, *args: Any) -> None:
        """Suppress request and credential logging."""

    def do_GET(self) -> None:  # pylint: disable=invalid-name  # HTTP handler API.
        """Return a bounded challenge or published encrypted material."""
        parsed = urllib.parse.urlsplit(self.path)
        challenge = urllib.parse.parse_qs(parsed.query).get("challenge", [""])[0]
        if len(challenge) > MAX_CHALLENGE:
            self.send_error(400)
            return
        if parsed.path not in ("/get", "/readyz", "/material"):
            self.send_error(404)
            return
        peer = ""
        if isinstance(self.connection, ssl.SSLSocket):
            certificate = self.connection.getpeercert(binary_form=True)
            if certificate is None:
                self.send_error(403)
                return
            peer = hashlib.sha256(certificate).hexdigest()
        if parsed.path == "/material" and not peer:
            self.send_error(403)
            return
        server = cast("DiagnosticHTTPServer", self.server)
        result = {
            "example": "certificate-origin",
            "challenge": challenge,
            "client_certificate_sha256": peer,
            "certificate_sha256": getattr(self.connection, "origin_fingerprint", ""),
            "listener_port": server.server_port,
        }
        if parsed.path == "/material":
            result["encrypted_material"] = json.loads(
                Path(server.material_file).read_text()
            )
        data = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class TLSServer(DiagnosticHTTPServer):
    """Use the current TLS material for each new connection."""

    def __init__(
        self, address: tuple[str, int], material: Material, material_file: str
    ) -> None:
        """Bind one diagnostic listener to its shared material source."""
        self.material = material
        self.material_file = material_file
        self.fingerprint = ""
        super().__init__(address, Handler)

    def get_request(self) -> tuple[ssl.SSLSocket, tuple[str, int]]:
        """Require a verified client before dispatching its HTTP request."""
        connection, address = self.socket.accept()
        connection.settimeout(10)
        if self.material.current is None:
            connection.close()
            message = "Certificate material is not ready"
            raise RuntimeError(message)
        context, fingerprint = self.material.current
        try:
            secured = context.wrap_socket(connection, server_side=True)
            cast("ConnectionFingerprint", secured).origin_fingerprint = fingerprint
        except Exception:
            connection.close()
            raise
        return secured, address


class TCPHandler(socketserver.StreamRequestHandler):
    """Echo one bounded challenge over an owned TCP origin connection."""

    def handle(self) -> None:
        """Make stale or unrelated backend responses distinguishable."""
        self.connection.settimeout(10)
        challenge = self.rfile.readline(MAX_CHALLENGE + 2)
        if len(challenge) > MAX_CHALLENGE + 1 or not challenge.endswith(b"\n"):
            return
        self.wfile.write(b"certificate-origin:" + challenge)


def run(config: dict[str, Any]) -> None:
    """Wait for provisioned material, then run the declared diagnostic listeners."""
    material = Material(
        lambda: vault_material(config["vault_url"], config["secret_name"])
    )
    while material.current is None:
        try:
            material.refresh()
        except (OSError, ValueError, KeyError, TypeError):
            time.sleep(10)
    servers: list[socketserver.BaseServer] = [
        TLSServer((BIND, port), material, config["material_file"])
        for port in config["mtls_ports"]
    ]
    plain = DiagnosticHTTPServer((BIND, config["http_port"]), Handler)
    plain.material_file = config["material_file"]
    servers.extend(
        [
            plain,
            socketserver.ThreadingTCPServer((BIND, config["tcp_port"]), TCPHandler),
        ]
    )
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    while True:
        time.sleep(30)
        try:
            material.refresh()
        except (OSError, ValueError, KeyError, TypeError):
            logging.getLogger(__name__).warning(
                "Certificate material refresh failed; previous TLS context retained"
            )


if __name__ == "__main__":
    run(json.loads(Path("/etc/origin-certificate/config.json").read_text()))
