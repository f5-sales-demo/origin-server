"""Source-controlled installer must reject unsafe paths before writing any file."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location(
            "install_origin", ROOT / "scripts/install_origin.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_install_is_repeatable_and_confined(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [
                {
                    "path": "/opt/origin-server/example",
                    "content": "fixture",
                    "permissions": "0600",
                }
            ]
            module.install_files(files, root)
            first = (root / "opt/origin-server/example").read_bytes()
            module.install_files(files, root)
            assert first == (root / "opt/origin-server/example").read_bytes()
            assert (root / "opt/origin-server/example").stat().st_mode & 511 == 384

    def test_invalid_paths_and_symlinks_fail_before_writes(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [
                {"path": "/opt/origin-server/good", "content": "good"},
                {"path": "/etc/../../escape", "content": "bad"},
            ]
            with pytest.raises(ValueError, match="escapes the origin"):
                module.install_files(files, root)
            assert not (root / "opt").exists()
            (root / "opt").symlink_to(root)
            with pytest.raises(ValueError, match="traverses a symlink"):
                module.install_files(files[:1], root)


if __name__ == "__main__":
    unittest.main()
