#!/usr/bin/env python3
"""Derive nginx routes, landing links, and readiness inventory from the manifest."""

import base64
import hashlib
import html
import json
from pathlib import Path

from application_manifest import load_manifest


def bind_juice_adapter(by_path: dict) -> None:
    """Recreate only declared Juice Shop containers when the preload changes."""
    compose_file = by_path["/opt/origin-server/docker-compose.yml"]
    adapter = by_path["/opt/origin-server/juice-shop-framing/preload.cjs"]["content"]
    adapter = adapter.replace(
        "__VT323_FONT_BASE64__",
        (
            Path(__file__).resolve().parents[1]
            / "provisioning/fonts/VT323-Regular.ttf.base64"
        )
        .read_text()
        .strip(),
    )
    by_path["/opt/origin-server/juice-shop-framing/preload.cjs"]["content"] = adapter
    digest = hashlib.sha256(adapter.encode()).hexdigest()
    content = compose_file["content"]
    mapping = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "provisioning/juice-country-mapping.json"
        ).read_text()
    )
    domain_config = "NODE_CONFIG=" + json.dumps(
        {"application": {"domain": "example.com"}, "ctf": {"countryMapping": mapping}},
        separators=(",", ":"),
    )
    content = content.replace(
        "    - NODE_ENV=ctf\n",
        "    - NODE_ENV=ctf\n    - '" + domain_config.replace("'", "''") + "'\n",
    )
    for index in range(1, 5):
        marker = f"    container_name: juice-shop-{index}\n"
        content = content.replace(
            marker,
            marker + "    labels:\n      org.f5.demo.adapter-sha256: " + digest + "\n",
        )
    compose_file["content"] = content


def bind_dvga_wsgi(root: Path, files: list[dict], by_path: dict) -> None:
    """Declare the native GraphQL worker adapter in every DVGA image."""
    files.append(
        {
            "path": "/opt/origin-server/dvga-adapter/dvga_wsgi.py",
            "content": (root / "scripts/dvga_wsgi.py").read_text(),
            "permissions": "0644",
        }
    )
    dockerfile = by_path["/opt/origin-server/dvga-adapter/Dockerfile"]
    dockerfile["content"] = dockerfile["content"].replace(
        "COPY adapt.py /tmp/adapt.py",
        "COPY adapt.py /tmp/adapt.py\nCOPY dvga_wsgi.py /opt/dvga/dvga_wsgi.py",
    )
    adapter = by_path["/opt/origin-server/dvga-adapter/adapt.py"]
    needle = "app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)"
    if adapter["content"].count(needle) != 1:
        message = "Native DVGA application wrapper changed"
        raise ValueError(message)
    adapter["content"] = adapter["content"].replace(
        needle,
        "from dvga_wsgi import NativeGraphQLThreadIsolation\\n"
        "app.wsgi_app = ProxyFix(NativeGraphQLThreadIsolation(app.wsgi_app), x_prefix=1)",
    )

    adapter["content"] = (
        adapter["content"]
        .replace(
            "from gevent import subprocess as cooperative_subprocess",
            "from dvga_wsgi import native_command_output",
        )
        .replace(
            "cooperative_subprocess.Popen(cmd, shell=True, stdout=cooperative_subprocess.PIPE, text=True).communicate()[0]",
            "native_command_output(cmd)",
        )
    )


def bind_csd_assets(root: Path, files: list[dict], by_path: dict) -> None:
    """Install exact pinned native scripts through the owned CSD static route."""
    asset_root = root / "provisioning/csd-assets"
    assets = json.loads((asset_root / "manifest.json").read_text())
    for name, specification in assets.items():
        if Path(name).name != name:
            message = "native CSD asset path invalid"
            raise ValueError(message)
        data = base64.b64decode(
            (asset_root / (name + ".base64")).read_text(), validate=False
        )
        if hashlib.sha256(data).hexdigest() != specification["sha256"]:
            message = "native CSD asset digest mismatch"
            raise ValueError(message)
        files.append(
            {
                "path": "/opt/origin-server/csd-demo/static/vendor/" + name,
                "content": data.decode(),
                "permissions": "0644",
            }
        )
    dockerfile = by_path["/opt/origin-server/csd-demo/Dockerfile"]
    dockerfile["content"] = dockerfile["content"].replace(
        "COPY templates/ templates/", "COPY templates/ templates/\nCOPY static/ static/"
    )


def bind_juice_raw_target(by_path: dict) -> None:
    """Preserve encoded path segments for the native Juice Shop route decoder."""
    nginx = by_path["/etc/nginx/nginx.conf"]
    marker = "    upstream juice_shop {"
    nginx["content"] = nginx["content"].replace(
        marker,
        "    map $request_uri $juice_native_uri {\n"
        '        default "";\n'
        "        ~^/juice-shop(/.*)$ $1;\n"
        "    }\n" + marker,
        1,
    )


def render(root: Path) -> list[dict]:
    """Reuse pinned provisioning files while deriving application declarations."""
    manifest = load_manifest(root / "provisioning/applications.json")
    files = json.loads((root / "provisioning/files.json").read_text())
    by_path = {item["path"]: item for item in files}
    bind_dvga_wsgi(root, files, by_path)
    bind_csd_assets(root, files, by_path)
    bind_juice_adapter(by_path)
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
        read_timeout = (
            f"        proxy_read_timeout {app['proxy_read_timeout_seconds']}s;\n"
            if "proxy_read_timeout_seconds" in app
            else ""
        )
        # A URI suffix makes nginx decode/re-encode path segments before dispatch.
        # Juice Shop's native parameter decoder must receive the original bytes.
        upstream += "$juice_native_uri" if app["id"] == "juice-shop" else "/"
        routes.append(f"""    location = {prefix} {{ return 308 {app["prefix"]}; }}
    location {app["prefix"]} {{
        proxy_pass {upstream};
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
{read_timeout}{affinity}    }}""")
    bind_juice_raw_target(by_path)
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
