"""Doctor JSON and a tiny HTTP health listener (family port 8789)."""

from __future__ import annotations

import json
import os
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from ansible_flow_mcp import __version__
from ansible_flow_mcp.catalog import catalog_dir, load_gallery
from ansible_flow_mcp.paths import hub_dir


def doctor_report() -> dict[str, Any]:
    gallery = load_gallery()
    ansible = shutil.which("ansible")
    hub = hub_dir()
    warnings: list[str] = []
    if not ansible:
        warnings.append("ansible CLI not on PATH")
    ok = catalog_dir().is_dir()
    return {
        "ok": ok,
        "version": __version__,
        "python": sys.version.split()[0],
        "catalogDir": str(catalog_dir()),
        "galleryCount": len(gallery),
        "ansible": ansible,
        "hubDir": str(hub),
        "hubInitialized": (hub / "inventory.yml").is_file(),
        "role": os.environ.get("ANSIBLE_FLOW_ROLE") or "legacy",
        "port": int(os.environ.get("ANSIBLE_FLOW_HTTP_PORT") or 8789),
        "warnings": warnings,
    }


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/health"}:
            report = doctor_report()
            body = json.dumps(report, indent=2).encode("utf-8")
            code = 200 if report.get("ok") else 503
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def serve_http(*, host: str = "0.0.0.0", port: int = 8789) -> None:
    os.environ["ANSIBLE_FLOW_HTTP_PORT"] = str(port)
    httpd = ThreadingHTTPServer((host, port), _Handler)
    sys.stderr.write(f"ansible-flow-mcp health on http://{host}:{port}/health\n")
    httpd.serve_forever()
