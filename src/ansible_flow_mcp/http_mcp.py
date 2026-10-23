"""Opt-in streamable HTTP MCP. Loopback unless the operator changes the bind.

Bearer token comes from a mode-0400 file (or ANSIBLE_FLOW_MCP_TOKEN_FILE).
The token value is never read from the environment and never logged.
"""

from __future__ import annotations

import hmac
import os
import secrets
import socket
import sys
import uuid
from pathlib import Path
from typing import Any

from ansible_flow_mcp.access_log import log_access

MCP_HTTP_TOKEN_FILENAME = "mcp.http.token"
DEFAULT_BIND = "localhost"
DEFAULT_PORT = 8790
_PATH = "/mcp"
_ANY_BIND = {"unspecified", "all", "*"}


def resolve_bind(host: str | None, *, default: str = DEFAULT_BIND) -> str:
    """Map the word ``unspecified`` to the in-container any-address."""
    value = (host or "").strip() or default
    if value in _ANY_BIND:
        return socket.INADDR_ANY
    return value


def mcp_http_token_path(root: Path) -> Path:
    override = (os.environ.get("ANSIBLE_FLOW_MCP_TOKEN_FILE") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path(root).expanduser().resolve() / MCP_HTTP_TOKEN_FILENAME


def ensure_mcp_http_token(root: Path) -> Path:
    """Create the bearer file (0400) if missing. Never logs the value."""
    path = mcp_http_token_path(root)
    if path.is_file() and path.stat().st_size > 0:
        try:
            os.chmod(path, 0o400)
        except OSError:
            pass
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o400)
    try:
        os.write(fd, (secrets.token_urlsafe(32) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, 0o400)
    return path


def load_mcp_http_token(root: Path) -> str:
    path = ensure_mcp_http_token(root)
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        path.unlink(missing_ok=True)
        path = ensure_mcp_http_token(root)
        token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"empty MCP HTTP token file: {path}")
    return token


def key_prefix(token: str) -> str:
    return "bearer:" + (token[:4] if token else "")


def _header(scope: dict[str, Any], name: str) -> str:
    want = name.lower().encode("latin1")
    for key, value in scope.get("headers") or []:
        if key.lower() == want:
            return value.decode("latin1")
    return ""


def _client_ip(scope: dict[str, Any]) -> str:
    client = scope.get("client")
    peer = str(client[0]) if client else "-"
    if (os.environ.get("ANSIBLE_FLOW_TRUST_PROXY") or "").strip().lower() in {"1", "true", "yes", "on"}:
        forwarded = _header(scope, "x-forwarded-for").split(",")[0].strip()
        if forwarded:
            return forwarded
    return peer


def bearer_matches(presented: str, expected: str) -> bool:
    got = presented.encode("utf-8")
    want = expected.encode("utf-8")
    if len(got) != len(want):
        return False
    return hmac.compare_digest(got, want)


class BearerAuthMiddleware:
    """Require Authorization: Bearer before any /mcp request reaches the app."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self._token = token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        request_id = _header(scope, "x-request-id").strip() or str(uuid.uuid4())
        source_ip = _client_ip(scope)
        method = str(scope.get("method") or "")
        if path.rstrip("/") != _PATH:
            log_access(
                action="mcp.http",
                outcome="not_found",
                actor="anonymous",
                source_ip=source_ip,
                request_id=request_id,
                method=method,
                path=path,
            )
            await _send_json(send, 404, {"ok": False, "error": "not found"})
            return
        header = _header(scope, "authorization")
        presented = ""
        if header.lower().startswith("bearer "):
            presented = header.split(None, 1)[1].strip()
        if not presented or not bearer_matches(presented, self._token):
            log_access(
                action="mcp.http",
                outcome="unauthorized",
                actor="anonymous",
                source_ip=source_ip,
                request_id=request_id,
                method=method,
                path=path,
            )
            await _send_json(send, 401, {"ok": False, "error": "unauthorized"})
            return
        log_access(
            action="mcp.http",
            outcome="ok",
            actor=key_prefix(self._token),
            source_ip=source_ip,
            request_id=request_id,
            method=method,
            path=path,
        )
        await self.app(scope, receive, send)


async def _send_json(send: Any, status: int, payload: dict[str, Any]) -> None:
    import json

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
                (b"x-content-type-options", b"nosniff"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _csv(name: str) -> list[str]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def apply_transport_security() -> None:
    """Host allow-list for DNS-rebinding checks. Default is loopback only."""
    from mcp.server.transport_security import TransportSecuritySettings

    from ansible_flow_mcp.server import mcp

    hosts = _csv("ANSIBLE_FLOW_MCP_ALLOWED_HOSTS") or [
        "localhost:*",
        "localhost",
    ]
    origins = _csv("ANSIBLE_FLOW_MCP_ALLOWED_ORIGINS")
    stateless = (os.environ.get("ANSIBLE_FLOW_MCP_HTTP_STATELESS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    json_response = (os.environ.get("ANSIBLE_FLOW_MCP_HTTP_JSON") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    mcp.settings.streamable_http_path = _PATH
    mcp.settings.stateless_http = stateless
    mcp.settings.json_response = json_response
    mcp.settings.log_level = "WARNING"
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def serve_mcp_http(*, root: Path, host: str | None = None, port: int | None = None) -> None:
    bind = resolve_bind(host or os.environ.get("ANSIBLE_FLOW_MCP_HTTP_BIND"), default=DEFAULT_BIND)
    listen_port = int(port if port is not None else (os.environ.get("ANSIBLE_FLOW_MCP_HTTP_PORT") or DEFAULT_PORT))
    token = load_mcp_http_token(root)
    token_path = mcp_http_token_path(root)

    from ansible_flow_mcp.server import mcp, use_role

    use_role("hub")
    mcp.settings.host = bind
    mcp.settings.port = listen_port
    apply_transport_security()
    app = BearerAuthMiddleware(mcp.streamable_http_app(), token=token)

    log_access(
        action="mcp.http.listen",
        outcome="ok",
        actor=key_prefix(token),
        source_ip=bind,
        request_id="-",
        path=_PATH,
        port=listen_port,
    )
    sys.stderr.write(
        f"mcp http listening on http://{bind}:{listen_port}{_PATH} token_file={token_path}\n"
    )

    import uvicorn

    config = uvicorn.Config(
        app,
        host=bind,
        port=listen_port,
        log_level="warning",
        access_log=False,
    )
    uvicorn.Server(config).run()
