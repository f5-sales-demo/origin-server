"""Exercise adapter transformations on synthetic upstream source fixtures."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class AdapterTests(unittest.TestCase):
    """Exercise the source contract and its failure paths."""

    def test_dvga_adapter_compiles_modified_application(self):
        """Verify the declared contract against a synthetic fixture."""
        files = json.loads((ROOT / "provisioning/files.json").read_text())
        source = next(
            item["content"]
            for item in files
            if item["path"].endswith("dvga-adapter/adapt.py")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "templates").mkdir()
            (root / "app.py").write_text(
                'app = Flask(__name__, static_folder="static/")\n'
            )
            (root / "templates/paste.html").write_text(
                '<img src="/static/logo.png"><script>fetch(\'/graphql\');new WebSocket("ws://{{host}}:{{port}}/subscriptions");</script>'
            )
            result = subprocess.run(  # noqa: S603 - owned adapter source with synthetic fixture
                [sys.executable, "-c", source.replace("/opt/dvga", str(root))],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            compile((root / "app.py").read_text(), "app", "exec")
            template = (root / "templates/paste.html").read_text()
            assert "{{ request.script_root }}/static/" in template
            assert "{{ request.script_root }}/graphql" in template
            assert "location.host" in template


if __name__ == "__main__":
    unittest.main()


def test_crapi_adapter_preserves_seeded_backend_role_navigation():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    source = next(
        item["content"]
        for item in files
        if item["path"].endswith("crapi-frontend/adapt.mjs")
    )
    assert 'userRole === "ROLE_PREDEFINE"' in source
    assert "Pinned crAPI role guard changed" in source
    assert "componentRole === roleTypes.ROLE_USER" in source


def test_crapi_chatbot_routes_to_its_pinned_dependency():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    compose = yaml.safe_load(
        next(
            item["content"]
            for item in files
            if item["path"].endswith("docker-compose.yml")
        )
    )
    assert "@sha256:" in compose["services"]["crapi-chatbot"]["image"]
    assert (
        "CHATBOT_SERVICE=crapi-chatbot:5002"
        in compose["services"]["crapi-web"]["environment"]
    )


def test_browser_tracking_header_is_scoped_to_application_origin():
    source = (ROOT / "scripts/verify_crapi_browser.mjs").read_text()
    assert "new URL(request.url()).origin === origin.origin" in source
    assert "newContext({ extraHTTPHeaders" not in source


def test_csd_templates_and_completion_derive_native_and_published_routes():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    for item in files:
        if "/csd-demo/templates/" in item["path"]:
            assert "/csd-demo/" not in item["content"].replace(
                "// checkout.js — EXTERNAL checkout script, served by app.py at /csd-demo/checkout.js and",
                "",
            )
    application = next(
        item["content"] for item in files if item["path"].endswith("csd-demo/app.py")
    )
    assert "url_for('checkout')" in application
    assert "fixture_id" in application


def test_restaurant_redoc_disables_external_google_font_loading():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    adapter = next(
        item["content"]
        for item in files
        if item["path"].endswith("adapt-restaurant.py")
    )
    assert "with_google_fonts=False" in adapter
