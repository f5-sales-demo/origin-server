"""Text evidence must retain functional verification without calling image capture."""

import json
import os
import shutil
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
application_receipts = import_module("application_receipts")
browser_observations = application_receipts.browser_observations
signup_observations = application_receipts.signup_observations
main = import_module("browser_runtime").main
NODE = shutil.which("node")
assert NODE is not None


def test_text_only_capture_never_calls_browser_or_creates_image(tmp_path):
    helper = (ROOT / "scripts/browser_evidence.mjs").as_uri()
    code = """
import assert from 'node:assert/strict';
import fs from 'node:fs';
const {captureScreenshot, evidenceMode} = await import(process.argv[1]);
assert.equal(evidenceMode, 'text-only');
let calls = 0;
const page = {screenshot: async () => {calls++; throw new Error('image capture called');}};
const result = await captureScreenshot(page, process.argv[2], 'evidence.png');
assert.equal(result, undefined);
assert.equal(calls, 0);
assert.deepEqual(fs.readdirSync(process.argv[2]), []);
assert.equal(JSON.stringify({screenshot: result}), '{}');
"""
    subprocess.run(  # noqa: S603 - fixed source-module regression on private temporary evidence
        [NODE, "--input-type=module", "-e", code, helper, str(tmp_path)],
        env=dict(os.environ, ORIGIN_EVIDENCE_MODE="text-only"),
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )


def test_invalid_evidence_mode_rejects_before_capture():
    code = "await import(process.argv[1]);"
    result = subprocess.run(  # noqa: S603 - fixed source-module rejection regression
        [
            NODE,
            "--input-type=module",
            "-e",
            code,
            (ROOT / "scripts/browser_evidence.mjs").as_uri(),
        ],
        env=dict(os.environ, ORIGIN_EVIDENCE_MODE="unknown"),
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode != 0
    assert "Invalid evidence mode" in result.stderr


@pytest.mark.parametrize("text_only", [False, True])
def test_matrix_propagates_mode_to_native_and_published_slices(tmp_path, text_only):
    manifest = {
        "applications": [
            {"id": "juice-shop", "ports": [3001]},
            {"id": "crapi", "ports": [8888]},
        ]
    }
    layers = [("https-www", "https://example.invalid")]
    with patch("application_receipts.subprocess.run") as run:
        browser_observations(tmp_path, manifest, layers, {}, text_only)
        signup_observations(tmp_path, manifest, layers, {}, text_only)
    commands = [call.args[0] for call in run.call_args_list]
    assert len(commands) == 6
    assert all(("--text-only" in command) == text_only for command in commands)
    assert any("--native" in command for command in commands)
    assert sum(command[1] == "crapi-signup" for command in commands) == 2


def test_installed_runner_binds_mode_and_shared_helper(tmp_path):
    provenance = {
        "source_commit": "fixture-source",
        "archive_sha256": "fixture-archive",
    }
    with (
        patch(
            "sys.argv",
            [
                "origin-browser-verify",
                "juice",
                "--base",
                "http://127.0.0.1:3001",
                "--output",
                str(tmp_path),
                "--text-only",
            ],
        ),
        patch("browser_runtime.Path.read_text", return_value=json.dumps(provenance)),
        patch("browser_runtime.Path.read_bytes", return_value=b"fixture-helper"),
        patch("browser_runtime.retain_evidence"),
        patch("browser_runtime.cleanup_container") as cleanup,
        patch("browser_runtime.subprocess.Popen") as popen,
    ):
        popen.return_value.__enter__.return_value.poll.return_value = 0
        popen.return_value.__enter__.return_value.wait.return_value = 0
        assert main() == 0
    command = popen.call_args.args[0]
    assert command[command.index("--env") + 1] == "ORIGIN_EVIDENCE_MODE=text-only"
    receipt = json.loads((tmp_path / "runtime-receipt.json").read_text())
    assert receipt["evidence_mode"] == "text-only"
    assert receipt["screenshots_reviewed"] is False
    assert receipt["evidence_helper_sha256"]
    cleanup.assert_called_once()
