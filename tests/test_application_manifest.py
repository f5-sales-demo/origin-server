"""Contract tests for the shared application inventory."""

import copy
import importlib.util
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class ManifestTests(unittest.TestCase):
    """Exercise the source contract and its failure paths."""

    def module(self):
        """Verify the declared contract against a synthetic fixture."""
        spec = importlib.util.spec_from_file_location(
            "application_manifest", ROOT / "scripts/application_manifest.py"
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_inventory_and_published_prefixes(self):
        """Verify the declared contract against a synthetic fixture."""
        module = self.module()
        manifest = module.load_manifest(ROOT / "provisioning/applications.json")
        assert len(manifest["applications"]) == 9
        assert len(module.url_map(manifest, "https://example.com")) == 9

    def test_missing_application_and_duplicate_port_fail(self):
        """Verify the declared contract against a synthetic fixture."""
        module = self.module()
        manifest = module.load_manifest(ROOT / "provisioning/applications.json")
        bad = copy.deepcopy(manifest)
        bad["applications"].pop()
        with pytest.raises(ValueError, match="exactly the nine"):
            module.validate_manifest(bad)
        bad = copy.deepcopy(manifest)
        bad["applications"][1]["ports"][0] = bad["applications"][0]["ports"][0]
        with pytest.raises(ValueError, match="conflicting native"):
            module.validate_manifest(bad)

    def test_prefix_escape_fails(self):
        """Verify the declared contract against a synthetic fixture."""
        module = self.module()
        manifest = module.load_manifest(ROOT / "provisioning/applications.json")
        bad = copy.deepcopy(manifest)
        bad["applications"][0]["pages"][0]["path"] = "../static/app.js"
        with pytest.raises(ValueError, match="escapes its application"):
            module.validate_manifest(bad)

    def test_content_identity_and_type_fail_closed(self):
        """Verify the declared contract against a synthetic fixture."""
        module = self.module()
        page = {"identity": "HTTPBIN", "content_type": "text/html"}
        assert not module.content_matches(page, "text/html", "Origin Server")
        assert not module.content_matches(page, "application/json", "HTTPBIN")
        assert module.content_matches(page, "text/html; charset=utf-8", "httpbin")


if __name__ == "__main__":
    unittest.main()
