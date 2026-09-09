"""Loopback hub admin HTTP server (stdlib). No HTTP MCP."""
from __future__ import annotations

import hmac
import json
import os
import sys
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ansible_flow_mcp.admin import routes
from ansible_flow_mcp.admin.routes import AdminError
from ansible_flow_mcp.hub.state import ensure_admin_token, load_admin_token, load_hub_state
from ansible_flow_mcp.paths import hub_dir


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8789
STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
}


def _default_host() -> str:
    return (os.environ.get("ANSIBLE_FLOW_ADMIN_BIND") or DEFAULT_HOST).strip() or DEFAULT_HOST


def _default_port() -> int:
    raw = (os.environ.get("ANSIBLE_FLOW_ADMIN_PORT") or "").strip()
    if raw:
        return int(raw)
    return DEFAULT_PORT


def _json_bytes(payload: dict[str, Any], status: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


class AdminHandler(BaseHTTPRequestHandler):
    hub_root: Path
    admin_token: str
    server_version = "ansible-flow-admin/1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 1_000_000:
            raise AdminError("request too large", status=413)
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdminError("invalid JSON") from exc
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise AdminError("JSON body must be an object")
        return data

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization") or ""
        prefix = "Bearer "
        if not header.startswith(prefix) and not header.lower().startswith("bearer "):
            return False
        presented = header.split(None, 1)[1].strip() if header.split() else ""
        expected = self.admin_token.encode("utf-8")
        got = presented.encode("utf-8")
        if len(got) != len(expected):
            # still compare to keep timing closer
            return hmac.compare_digest(expected, expected) and False
        return hmac.compare_digest(expected, got)

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        status, body, ctype = _json_bytes({"ok": False, "error": "unauthorized"}, 401)
        self._send(status, body, ctype)
        return False

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in {"/", "/admin"}:
                self.send_response(302)
                self.send_header("Location", "/admin/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/health":
                from ansible_flow_mcp.http_health import doctor_report

                report = doctor_report()
                report.setdefault("service", "ansible-flow-mcp")
                status = 200 if report.get("ok") else 503
                self._send(*_json_bytes(report, status))
                return
            if path == "/admin/" or path == "/admin/index.html":
                self._send_static("index.html")
                return
            if path == "/admin/app.js":
                self._send_static("app.js")
                return
            if path == "/admin/styles.css":
                self._send_static("styles.css")
                return
            if path.startswith("/v1/"):
                if not self._require_auth():
                    return
                self._dispatch("GET", path, {}, parse_qs(parsed.query))
                return
            self._send(*_json_bytes({"ok": False, "error": "not found"}, 404))
        except Exception as exc:  # noqa: BLE001
            self._handle_exc(exc)

    def do_POST(self) -> None:  # noqa: N802
        self._mutate("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._mutate("PATCH")

    def do_PUT(self) -> None:  # noqa: N802
        self._mutate("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._mutate("DELETE")

    def _mutate(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if not path.startswith("/v1/"):
                self._send(*_json_bytes({"ok": False, "error": "not found"}, 404))
                return
            if not self._require_auth():
                return
            body = self._read_json() if method != "DELETE" else self._read_json()
            self._dispatch(method, path, body, parse_qs(parsed.query))
        except Exception as exc:  # noqa: BLE001
            self._handle_exc(exc)

    def _send_static(self, name: str) -> None:
        if name not in _STATIC_FILES:
            self._send(*_json_bytes({"ok": False, "error": "not found"}, 404))
            return
        path = STATIC_DIR / name
        data = path.read_bytes()
        self._send(200, data, _STATIC_FILES[name])

    def _handle_exc(self, exc: BaseException) -> None:
        if isinstance(exc, AdminError):
            self._send(*_json_bytes({"ok": False, "error": exc.message}, exc.status))
            return
        if isinstance(exc, FileNotFoundError):
            self._send(*_json_bytes({"ok": False, "error": str(exc)}, 404))
            return
        if isinstance(exc, ValueError):
            self._send(*_json_bytes({"ok": False, "error": str(exc)}, 400))
            return
        self._send(*_json_bytes({"ok": False, "error": "internal error"}, 500))

    def _dispatch(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
        query: dict[str, list[str]],
    ) -> None:
        root = self.hub_root
        parts = [unquote(p) for p in path.strip("/").split("/") if p]

        def ok(payload: dict[str, Any], status: int = 200) -> None:
            self._send(*_json_bytes(payload, status))

        # /v1/...
        if parts[:1] != ["v1"] or len(parts) < 2:
            self._send(*_json_bytes({"ok": False, "error": "not found"}, 404))
            return
        rest = parts[1:]

        if rest == ["status"] and method == "GET":
            ok(routes.status(root))
            return
        if rest == ["nodes"] and method == "GET":
            st = routes.status(root)
            ok({"ok": True, "nodes": st.get("spoke_nodes") or [], "all_nodes": st.get("nodes") or []})
            return
        if rest == ["tokens"] and method == "POST":
            ok(routes.issue_join_token(root, body), 201)
            return
        if len(rest) == 2 and rest[0] == "nodes" and method == "PATCH":
            ok(routes.patch_node(root, rest[1], body))
            return
        if len(rest) == 2 and rest[0] == "nodes" and method == "DELETE":
            ok(routes.revoke(root, rest[1]))
            return
        if len(rest) == 3 and rest[0] == "nodes" and rest[2] == "ping" and method == "POST":
            ok(routes.ping_spoke(root, rest[1]))
            return
        if rest == ["targets"] and method == "GET":
            st = routes.status(root)
            ok({"ok": True, "targets": st.get("target_nodes") or []})
            return
        if rest == ["targets"] and method == "POST":
            ok(routes.create_target(root, body), 201)
            return
        if len(rest) == 2 and rest[0] == "targets" and method == "PATCH":
            ok(routes.patch_target(root, rest[1], body))
            return
        if len(rest) == 2 and rest[0] == "targets" and method == "DELETE":
            ok(routes.remove_target(root, rest[1]))
            return
        if rest == ["groups"] and method == "GET":
            ok(routes.groups(root))
            return
        if rest == ["groups"] and method == "POST":
            ok(routes.create_group(root, body), 201)
            return
        if len(rest) == 2 and rest[0] == "groups" and method == "DELETE":
            ok(routes.delete_group(root, rest[1]))
            return
        if len(rest) == 3 and rest[0] == "groups" and rest[2] == "members" and method == "PUT":
            ok(routes.set_members(root, rest[1], body))
            return
        if rest == ["audit"] and method == "GET":
            raw_limit = (query.get("limit") or ["100"])[0]
            try:
                limit = int(raw_limit)
            except ValueError as exc:
                raise AdminError("limit must be an integer") from exc
            ok(routes.audit(root, limit=limit))
            return

        self._send(*_json_bytes({"ok": False, "error": "not found"}, 404))


def make_server(
    *,
    root: Path | None = None,
    host: str | None = None,
    port: int | None = None,
) -> ThreadingHTTPServer:
    hub_root = Path(root or hub_dir()).expanduser().resolve()
    load_hub_state(hub_root)
    ensure_admin_token(hub_root)
    token = load_admin_token(hub_root)
    bind_host = host if host is not None else _default_host()
    bind_port = _default_port() if port is None else int(port)
    handler = partial(AdminHandler)
    # bind attributes used by instances
    AdminHandler.hub_root = hub_root
    AdminHandler.admin_token = token
    httpd = ThreadingHTTPServer((bind_host, bind_port), handler)
    return httpd


def serve_admin(
    *,
    root: Path | None = None,
    host: str | None = None,
    port: int | None = None,
) -> None:
    httpd = make_server(root=root, host=host, port=port)
    bind_host, bind_port = httpd.server_address[:2]
    token_path = ensure_admin_token(Path(root or hub_dir()))
    sys.stdout.write(
        f"admin console http://{bind_host}:{bind_port}/admin/\n"
        f"token file {token_path} (not printed)\n"
        "HTTP MCP is not enabled\n"
    )
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
