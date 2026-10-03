"""Contract tests for the shared application inventory."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

import pytest
import yaml

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

    def test_serving_replicas_do_not_exit_after_request_quota(self):
        """Continuous benign traffic must not synchronize application restarts."""

        files = json.loads((ROOT / "provisioning/files.json").read_text())
        compose = yaml.safe_load(
            next(
                item["content"]
                for item in files
                if item["path"].endswith("docker-compose.yml")
            )
        )
        for name, service in compose["services"].items():
            if name.startswith("restaurant-") and name != "restaurant-db":
                assert "--limit-max-requests" not in service["command"]

    def test_php_sessions_use_the_shared_replica_store(self):
        """The authenticated fixture must survive routing to another replica."""
        files = json.loads((ROOT / "provisioning/files.json").read_text())
        config = next(
            item["content"]
            for item in files
            if item["path"].endswith("dvwa-fpm/www.conf")
        )
        assert "php_admin_value[session.save_path] = /var/lib/php/sessions" in config

    def test_content_identity_and_type_fail_closed(self):
        """Verify the declared contract against a synthetic fixture."""
        module = self.module()
        page = {"identity": "HTTPBIN", "content_type": "text/html"}
        assert not module.content_matches(page, "text/html", "Origin Server")
        assert not module.content_matches(page, "application/json", "HTTPBIN")
        assert module.content_matches(page, "text/html; charset=utf-8", "httpbin")


if __name__ == "__main__":
    unittest.main()


def test_direct_and_proxy_clients_have_stable_nonempty_juice_affinity():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    nginx = next(
        item["content"] for item in files if item["path"] == "/etc/nginx/nginx.conf"
    )
    assert "map $http_x_forwarded_for $juice_affinity" in nginx
    assert '"" $remote_addr;' in nginx
    assert "hash $juice_affinity consistent;" in nginx
