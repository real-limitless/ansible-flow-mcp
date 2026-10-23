#!/usr/bin/env python3
"""Liveness: sshd, admin /health, and (when enabled) anonymous /mcp is 401."""

from __future__ import annotations

import os
import socket
import sys
import urllib.error
import urllib.request


def main() -> int:
    socket.create_connection(("localhost", 22), 3).close()
    admin_port = (os.environ.get("ANSIBLE_FLOW_ADMIN_PORT") or "8789").strip()
    with urllib.request.urlopen(f"http://localhost:{admin_port}/health", timeout=3) as resp:
        if resp.status != 200:
            return 1
        resp.read()
    flag = (os.environ.get("ANSIBLE_FLOW_MCP_HTTP") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        port = (os.environ.get("ANSIBLE_FLOW_MCP_HTTP_PORT") or "8790").strip()
        try:
            urllib.request.urlopen(f"http://localhost:{port}/mcp", timeout=3)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                return 1
        else:
            return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(1)
