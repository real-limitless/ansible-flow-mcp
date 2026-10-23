"""Doctor JSON. The HTTP listener lives in http_mcp (health + authenticated /mcp)."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any

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


def serve_http(*, host: str = "0.0.0.0", port: int = 8789) -> None:
    """HTTP entry: /health plus bearer-authenticated streamable MCP at /mcp."""
    from ansible_flow_mcp.http_mcp import serve_http as serve_mcp_http

    serve_mcp_http(host=host, port=port)
