"""Exercise adapter transformations on synthetic upstream source fixtures."""

import base64
import json
import shutil
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


def test_httpbin_assets_forms_and_spec_use_request_prefix():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    adapter = next(
        item["content"]
        for item in files
        if item["path"].endswith("httpbin-adapter/adapt.py")
    )
    assert "{{ request.script_root }}" in adapter
    assert "template['basePath'] = '/httpbin'" not in adapter
    assert "document['basePath'] = request.script_root" in adapter
    assert "@app.before_request" not in adapter


def test_restaurant_native_prefix_adapter_strips_only_its_declared_route():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    adapter = next(
        item["content"]
        for item in files
        if item["path"].endswith("adapt-restaurant.py")
    )
    assert "scope['path'].startswith('/restaurant/')" in adapter
    assert "scope['path'][len('/restaurant'):]" in adapter


def test_crapi_vehicle_image_adapter_preserves_published_asset_base():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    adapter = next(
        item["content"]
        for item in files
        if item["path"].endswith("crapi-frontend/adapt.mjs")
    )
    assert "vehicle.model.vehicle_img" in adapter
    assert "new URL(vehicle.model.vehicle_img" in adapter


def test_crapi_mechanic_adapter_uses_canonical_endpoint_without_redirect():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    adapter = next(
        item["content"]
        for item in files
        if item["path"].endswith("crapi-frontend/adapt.mjs")
    )
    assert "GET_MECHANICS" in adapter
    assert "api/mechanic/" in adapter


def test_juice_native_prefix_routes_api_assets_before_spa_fallback():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    adapter = next(
        item["content"]
        for item in files
        if item["path"].endswith("juice-shop-framing/preload.cjs")
    )
    assert "request.url.startsWith('/juice-shop/')" in adapter
    assert "request.url.slice('/juice-shop'.length)" in adapter


def test_crapi_native_frontend_strips_published_prefix_before_dispatch():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    dockerfile = next(
        item["content"]
        for item in files
        if item["path"].endswith("crapi-frontend/Dockerfile")
    )
    assert "rewrite ^/crapi/(.*)$ /$1 last" in dockerfile


def test_crapi_signup_consumes_success_response_before_navigation():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    adapter = next(
        item["content"]
        for item in files
        if item["path"].endswith("crapi-frontend/adapt.mjs")
    )
    assert "if (receivedResponse.ok) return response;" in adapter
    assert "return response.json();" in adapter


def test_juice_local_font_adapter_is_repeatable(tmp_path):
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    adapter = next(
        item["content"]
        for item in files
        if item["path"].endswith("juice-shop-framing/preload.cjs")
    )
    font = (ROOT / "provisioning/fonts/VT323-Regular.ttf.base64").read_text().strip()
    native = tmp_path / "juice-shop" / "frontend" / "dist"
    native.mkdir(parents=True)
    page = native / "index.html"
    page.write_text(
        '<html><head><link href="https://fonts.googleapis.com/css2?family=VT323" rel="stylesheet"></head><body>fixture</body></html>'
    )
    script = tmp_path / "adapter.cjs"
    script.write_text(
        adapter.replace("__VT323_FONT_BASE64__", font).replace(
            "/juice-shop/frontend", str(tmp_path / "juice-shop" / "frontend")
        )
        + "\nfs.readFile("
        + repr(str(page))
        + ",()=>{fs.readFile("
        + repr(str(page))
        + ",()=>{});});"
    )
    result = subprocess.run(  # noqa: S603 - fixed synthetic adapter fixture
        [shutil.which("node") or "/usr/bin/node", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    html = page.read_text()
    assert "fonts.googleapis.com" not in html
    assert html.count("data-origin-local-font") == 1
    assert (
        native / "frontend/assets/public/fonts/VT323-Regular.ttf"
    ).read_bytes() == base64.b64decode(font)
