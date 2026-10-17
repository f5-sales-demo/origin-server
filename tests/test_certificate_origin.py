"""Exercise actual TLS peer authentication, renewal, and synthetic origin traffic."""

import hashlib
import http.client
import importlib.util
import json
import os
import socket
import socketserver
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "certificate_origin", Path(__file__).parents[1] / "scripts/certificate_origin.py"
)
ORIGIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORIGIN)


class TCPTests(unittest.TestCase):
    def test_challenge_crosses_real_tcp_connection(self):
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), ORIGIN.TCPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=5) as client:
                client.sendall(b"unique-challenge\n")
                self.assertEqual(client.recv(1024), b"certificate-origin:unique-challenge\n")
        finally:
            server.shutdown()
            server.server_close()


@unittest.skipUnless(hasattr(os, "memfd_create"), "TLS memory files require Linux")
class TLSOriginTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="origin-certificate-test-")
        self.root = Path(self.work.name)
        self.root.chmod(0o700)
        self.openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-days", "1", "-subj", "/CN=synthetic-ca", "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        self.issue("server", "serverAuth", "DNS:localhost")
        self.issue("client", "clientAuth", "DNS:synthetic-client")
        self.issue("renewed", "clientAuth", "DNS:synthetic-client")
        self.material = {
            "certificate": (self.root / "server.pem").read_text(),
            "private_key": (self.root / "server.key").read_text(),
            "client_ca": (self.root / "ca.pem").read_text(),
        }
        self.holder = ORIGIN.Material(lambda: self.material)
        self.holder.refresh()
        store = self.root / "encrypted.json"
        store.write_text(json.dumps({"synthetic": "string:///encrypted-material"}))
        self.server = ORIGIN.TLSServer(("127.0.0.1", 0), self.holder, str(store))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.work.cleanup()

    def openssl(self, *args):
        result = subprocess.run(["openssl", *args], cwd=self.root, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, "synthetic certificate generation failed")

    def issue(self, name, usage, san):
        self.openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", name + ".key", "-out", name + ".csr", "-subj", "/CN=" + name)
        (self.root / "extensions").write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=" + usage + "\nsubjectAltName=" + san + "\n")
        self.openssl("x509", "-req", "-in", name + ".csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-days", "1", "-extfile", "extensions", "-out", name + ".pem")

    def request(self, name, path="/get?challenge=unique-request", hostname="localhost"):
        context = ssl.create_default_context(cafile=str(self.root / "ca.pem"))
        if name:
            context.load_cert_chain(self.root / (name + ".pem"), self.root / (name + ".key"))
        connection = http.client.HTTPSConnection(hostname, self.server.server_port, context=context, timeout=5)
        try:
            connection.request("GET", path, headers={"X-Forwarded-Client-Cert": "forged"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            return json.loads(response.read())
        finally:
            connection.close()

    def fingerprint(self, name):
        return hashlib.sha256(ssl.PEM_cert_to_DER_cert((self.root / (name + ".pem")).read_text())).hexdigest()

    def test_peer_fingerprint_and_renewal(self):
        original = self.request("client")
        renewed = self.request("renewed")
        self.assertEqual(original["client_certificate_sha256"], self.fingerprint("client"))
        self.assertEqual(renewed["client_certificate_sha256"], self.fingerprint("renewed"))
        self.assertNotEqual(original["client_certificate_sha256"], renewed["client_certificate_sha256"])
        self.assertEqual(original["certificate_sha256"], self.fingerprint("server"))
        self.assertEqual(original["challenge"], "unique-request")

    def test_missing_foreign_client_and_wrong_hostname_fail(self):
        with self.assertRaises((ssl.SSLError, ConnectionResetError)):
            self.request(None)
        self.openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "foreign.key", "-out", "foreign.pem", "-days", "1", "-subj", "/CN=foreign-client")
        with self.assertRaises((ssl.SSLError, ConnectionResetError)):
            self.request("foreign")
        with self.assertRaises(ssl.SSLError):
            self.request("client", hostname="127.0.0.1")

    def test_authenticated_encrypted_material(self):
        result = self.request("client", path="/material?challenge=store-request")
        self.assertEqual(result["encrypted_material"], {"synthetic": "string:///encrypted-material"})
        self.assertEqual(result["client_certificate_sha256"], self.fingerprint("client"))

    def test_failed_refresh_preserves_healthy_context(self):
        before = self.holder.current
        self.material["private_key"] = "invalid"
        with self.assertRaises(ssl.SSLError):
            self.holder.refresh()
        self.assertIs(self.holder.current, before)
        self.assertEqual(self.request("client")["certificate_sha256"], self.fingerprint("server"))


if __name__ == "__main__":
    unittest.main()
