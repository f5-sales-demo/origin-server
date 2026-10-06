"""Bind database fixture bytes to the native media artifact; native decode evidence is separate."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_seeded_video_bytes_match_native_media():
    metadata = json.loads(
        (ROOT / "provisioning/fixtures/synthetic-video.json").read_text()
    )
    video = bytes.fromhex(metadata["hex"])
    assert hashlib.sha256(video).hexdigest() == metadata["sha256"]
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    seed = next(
        item["content"]
        for item in files
        if item["path"] == "/usr/local/bin/demo-catalog-fixtures"
    )
    assert video.hex() in seed
    assert hashlib.sha256(video).hexdigest() in seed
    assert (
        "decode('0000001c6674797069736f6d0000020069736f6d69736f326d703431'," not in seed
    )
    assert "PERFORM lo_put" in seed
    assert "lo_get(video)<>decode" in seed
