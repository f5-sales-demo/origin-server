"""Exercise adapter transformations on synthetic upstream source fixtures."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
            assert "/dvga/static/" in template
            assert "/dvga/graphql" in template
            assert "location.host" in template


if __name__ == "__main__":
    unittest.main()
