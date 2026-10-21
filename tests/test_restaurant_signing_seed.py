"""Every native RESTaurant replica uses the declared synthetic signing seed."""

import json
from pathlib import Path

import yaml


def test_all_four_replicas_share_declared_signing_environment():
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / "provisioning/files.json").read_text())
    compose = yaml.safe_load(
        next(r["content"] for r in rows if r["path"].endswith("docker-compose.yml"))
    )
    for index in range(1, 5):
        environment = compose["services"]["restaurant-" + str(index)]["environment"]
        assert environment.count("JWT_SECRET_KEY=97953") == 1
