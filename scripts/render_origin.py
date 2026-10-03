#!/usr/bin/env python3
"""Derive nginx routes, landing links, and readiness inventory from the manifest."""

import hashlib
import html
import json
from pathlib import Path

from application_manifest import load_manifest


def render(root: Path) -> list[dict]:
    """Reuse pinned provisioning files while deriving application declarations."""
    manifest = load_manifest(root / "provisioning/applications.json")
    files = json.loads((root / "provisioning/files.json").read_text())
    by_path = {item["path"]: item for item in files}
    compose_file = by_path["/opt/origin-server/docker-compose.yml"]
    adapter = by_path["/opt/origin-server/juice-shop-framing/preload.cjs"]["content"]
    digest = hashlib.sha256(adapter.encode()).hexdigest()
    content = compose_file["content"]
    for index in range(1, 5):
        marker = f"    container_name: juice-shop-{index}\n"
        content = content.replace(
            marker,
            marker + "    labels:\n      org.f5.demo.adapter-sha256: " + digest + "\n",
        )
    compose_file["content"] = content
    app_list = manifest["applications"]
    by_path["/var/www/html/index.html"]["content"] = (
        "<!doctype html><html><head><title>Origin Server</title></head>"
        "<body><h1>Origin Server</h1><ul>"
        + "".join(
            '<li><a href="'
            + app["prefix"]
            + '">'
            + html.escape(app["name"])
            + "</a></li>"
            for app in app_list
        )
        + '</ul><a href="/health">Health Check</a></body></html>\n'
    )
    readiness = by_path["/usr/local/bin/demo-origin-ready"]
    source = readiness["content"]
    start = source.index("FAMILIES = {")
    end = source.index("\nCRAPI =", start)
    families = {app["id"]: app["ports"][0] for app in app_list if app["id"] != "crapi"}
    readiness["content"] = (
        source[:start] + "FAMILIES = " + repr(families) + source[end:]
    )
    routes = []
    for app in app_list:
        prefix = app["prefix"].rstrip("/")
        upstream = (
            "http://127.0.0.1:8888"
            if app["id"] == "crapi"
            else "http://" + app["upstream"]
        )
        affinity = (
            '        add_header Set-Cookie "dvga_replica=$dvga_affinity; Path=/dvga/; HttpOnly; SameSite=Lax" always;\n'
            if app["id"] == "dvga"
            else ""
        )
        routes.append(f"""    location = {prefix} {{ return 308 {app["prefix"]}; }}
    location {app["prefix"]} {{
        proxy_pass {upstream}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Prefix {prefix};
        proxy_redirect ~^/(?!{app["id"]}(?:/|$))(.*)$ {prefix}/$1;
        proxy_cookie_path / {app["prefix"]};
{affinity}    }}""")
    site = by_path["/etc/nginx/sites-available/origin-server"]["content"]
    second = site[site.index("server {", site.index("server {") + 1) :]
    health = json.dumps(
        {
            "status": "healthy",
            "component": "origin-server",
            "applications": [app["id"] for app in app_list],
        },
        separators=(",", ":"),
    )
    by_path["/etc/nginx/sites-available/origin-server"]["content"] = (
        f"""server {{
    listen 80 reuseport backlog=4096;
    server_name _;
    location = /health {{ default_type application/json; return 200 '{health}'; }}
    location = / {{ root /var/www/html; try_files /index.html =404; }}
    location / {{ return 404; }}
"""
        + "\n".join(routes)
        + "\n}\n\n"
        + second
    )
    return files
