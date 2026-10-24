"""Authenticated streamable HTTP MCP on /mcp, plus unauthenticated /health.

Stdio (`hub session`, bare `ansible-flow-mcp`) is unchanged. This listener
refuses to start unless an operator bearer is configured. That bearer is not
a spoke join token and not the admin portal token.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from ansible_flow_mcp.http_health import doctor_report

MCP_PATH = "/mcp"
_CLIENT_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
_PUBLIC_ROUTES = False
_APP: Any = None
_SEEN_SESSIONS: set[str] = set()
_SEEN_LOCK = threading.Lock()
_RATE_LOCK = threading.Lock()
_RATE_HITS: deque[float] = deque()
_DENY_LOCK = threading.Lock()
_DENY_HITS: deque[float] = deque()
_ALLOWED_HOSTS: list[str] = []


class McpAuthConfigError(RuntimeError):
    """HTTP MCP was asked to listen without an operator bearer."""


def load_mcp_bearer_token() -> str:
    """Return the operator bearer. Empty config is an error, never a default.

    The file is read on every call so replacing it does not require a restart.
    The value is not cached on the process.
    """
    env = (os.environ.get("ANSIBLE_FLOW_MCP_TOKEN") or "").strip()
    if env:
        return env
    raw_path = (os.environ.get("ANSIBLE_FLOW_MCP_TOKEN_FILE") or "").strip()
    if raw_path:
        path = Path(raw_path).expanduser()
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise McpAuthConfigError(
                f"refusing HTTP MCP: cannot read ANSIBLE_FLOW_MCP_TOKEN_FILE ({exc})"
            ) from exc
        if token:
            _warn_token_file_mode(path)
            return token
    raise McpAuthConfigError(
        "refusing HTTP MCP: set ANSIBLE_FLOW_MCP_TOKEN or ANSIBLE_FLOW_MCP_TOKEN_FILE. "
        "Stdio (ansible-flow-mcp hub session) does not need this secret. "
        "An empty token does not start an anonymous listener."
    )


def bearer_matches(header: str | None, expected: str) -> bool:
    if not header or not expected:
        return False
    parts = header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    presented = parts[1].strip().encode("utf-8")
    wanted = expected.encode("utf-8")
    if len(presented) != len(wanted):
        hmac.compare_digest(wanted, wanted)
        return False
    return hmac.compare_digest(presented, wanted)


def _warn_token_file_mode(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & 0o077:
        sys.stderr.write(
            f"warning: {path} is readable by group or other; tighten permissions if this is not a mounted secret\n"
        )


_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _request_id(headers: dict[str, str]) -> str:
    raw = (headers.get("x-request-id") or "").strip()
    if _REQUEST_ID_RE.fullmatch(raw):
        return raw
    return uuid.uuid4().hex


def _trust_proxy() -> bool:
    return (os.environ.get("ANSIBLE_FLOW_TRUST_PROXY") or "").strip().lower() in {"1", "true", "yes", "on"}


def _peer_ip(scope: Scope, headers: dict[str, str]) -> str:
    client = scope.get("client")
    peer = str(client[0]) if client else "-"
    if _trust_proxy():
        forwarded = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            return forwarded[:64]
    return peer


def listen_hosts(subnets: str, local_ips: list[str]) -> list[str]:
    """Loopback plus local addresses inside the allowed CIDRs.

    An address on any other interface is left unbound so the MCP port is not
    open there.
    """
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for part in subnets.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError as exc:
            raise ValueError(f"invalid ANSIBLE_FLOW_HTTP_BIND_SUBNETS entry {part!r}") from exc
    if not nets:
        raise ValueError("ANSIBLE_FLOW_HTTP_BIND_SUBNETS is set but empty")
    chosen = ["127.0.0.1"]
    seen = {"127.0.0.1"}
    for raw in local_ips:
        try:
            addr = ipaddress.ip_address(str(raw).strip())
        except ValueError:
            continue
        if not isinstance(addr, ipaddress.IPv4Address) or addr.is_loopback:
            continue
        text = str(addr)
        if text in seen:
            continue
        if any(addr in net for net in nets):
            chosen.append(text)
            seen.add(text)
    return chosen


def local_ipv4s() -> list[str]:
    """IPv4 addresses marked local in the kernel trie. Empty if unreadable."""
    try:
        text = Path("/proc/net/fib_trie").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[str] = []
    previous = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|-- "):
            previous = stripped[4:].strip()
            continue
        if stripped.startswith("/32 host LOCAL") and previous:
            found.append(previous)
            previous = ""
    return found


def _client_id(header: str | None) -> str:
    raw = (header or os.environ.get("ANSIBLE_FLOW_MCP_CLIENT_ID") or "operator").strip()
    cleaned = _CLIENT_ID_RE.sub("", raw)[:64]
    return cleaned or "operator"


def _public_host() -> str:
    return (os.environ.get("ANSIBLE_FLOW_PUBLIC_HOST") or "ansible-flow-mcp.z.srl").strip()


def allowed_hosts() -> list[str]:
    hosts = [
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
        "[::1]",
        "[::1]:*",
    ]
    public = _public_host()
    if public:
        hosts.extend([public, f"{public}:*"])
    extra = os.environ.get("ANSIBLE_FLOW_MCP_ALLOWED_HOSTS") or ""
    for item in extra.split(","):
        item = item.strip()
        if not item:
            continue
        hosts.append(item)
        if ":" not in item and not item.endswith(":*"):
            hosts.append(f"{item}:*")
    if os.environ.get("PYTEST_CURRENT_TEST"):
        hosts.extend(["testserver", "testserver:*"])
    # preserve order, drop dupes
    seen: set[str] = set()
    out: list[str] = []
    for host in hosts:
        if host not in seen:
            seen.add(host)
            out.append(host)
    return out


def allowed_origins() -> list[str]:
    public = _public_host()
    origins = [
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
    ]
    if public:
        origins.extend(
            [
                f"https://{public}",
                f"https://{public}:*",
                f"http://{public}",
                f"http://{public}:*",
            ]
        )
    extra = os.environ.get("ANSIBLE_FLOW_MCP_ALLOWED_ORIGINS") or ""
    for item in extra.split(","):
        item = item.strip()
        if item:
            origins.append(item)
    return origins


def host_allowed(host: str | None, patterns: list[str] | None = None) -> bool:
    if not host:
        return False
    patterns = patterns if patterns is not None else _ALLOWED_HOSTS or allowed_hosts()
    if host in patterns:
        return True
    for allowed in patterns:
        if allowed.endswith(":*") and host.startswith(allowed[:-2] + ":"):
            return True
    return False


def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def rate_limit_allows() -> bool:
    """Shared process bucket. <=0 disables the limit."""
    limit = _int_env("ANSIBLE_FLOW_MCP_RATE_PER_MINUTE", 120)
    if limit <= 0:
        return True
    now = time.monotonic()
    with _RATE_LOCK:
        while _RATE_HITS and now - _RATE_HITS[0] > 60:
            _RATE_HITS.popleft()
        if len(_RATE_HITS) >= limit:
            return False
        _RATE_HITS.append(now)
        return True


def _audit(event: str, **fields: Any) -> None:
    try:
        from ansible_flow_mcp.hub.state import audit_log, load_hub_state

        state = load_hub_state()
    except (FileNotFoundError, OSError, ValueError):
        return
    audit_log(state, event, transport="http", **fields)


def _audit_denied(client_id: str) -> None:
    """Cap deny lines so a scanner cannot fill the hub volume."""
    now = time.monotonic()
    with _DENY_LOCK:
        while _DENY_HITS and now - _DENY_HITS[0] > 60:
            _DENY_HITS.popleft()
        if len(_DENY_HITS) >= 30:
            return
        _DENY_HITS.append(now)
    _audit("mcp_http_denied", client_id=client_id)


def _audit_session(headers: dict[str, str], client_id: str) -> None:
    session = (headers.get("mcp-session-id") or "").strip()
    if session:
        with _SEEN_LOCK:
            if session in _SEEN_SESSIONS:
                return
            if len(_SEEN_SESSIONS) > 10000:
                _SEEN_SESSIONS.clear()
            _SEEN_SESSIONS.add(session)
        _audit("mcp_http_session", client_id=client_id, session_id=session[:128])
        return
    _audit("mcp_http_session", client_id=client_id)


def _health_body() -> dict[str, Any]:
    report = doctor_report()
    report["mcp"] = {
        "path": MCP_PATH,
        "transport": "streamable-http",
        "auth": "bearer",
    }
    return report


def _health_response() -> JSONResponse:
    report = _health_body()
    code = 200 if report.get("ok") else 503
    return JSONResponse(report, status_code=code, headers={"Cache-Control": "no-store"})


def _install_public_routes() -> None:
    global _PUBLIC_ROUTES
    if _PUBLIC_ROUTES:
        return
    from ansible_flow_mcp.server import mcp

    @mcp.custom_route("/health", methods=["GET", "HEAD"])
    async def health(_request: Request) -> Response:
        return _health_response()

    @mcp.custom_route("/", methods=["GET", "HEAD"])
    async def root(_request: Request) -> Response:
        return _health_response()

    _PUBLIC_ROUTES = True


def configure_http_security() -> None:
    """Pin Host allowlist before the streamable session manager is created."""
    global _ALLOWED_HOSTS
    from mcp.server.transport_security import TransportSecuritySettings

    from ansible_flow_mcp.server import mcp

    _ALLOWED_HOSTS = allowed_hosts()
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(_ALLOWED_HOSTS),
        allowed_origins=allowed_origins(),
    )
    mcp.settings.streamable_http_path = MCP_PATH
    mcp.settings.max_sessions = _int_env("ANSIBLE_FLOW_MCP_MAX_SESSIONS", 32)
    host = (os.environ.get("ANSIBLE_FLOW_HTTP_HOST") or "0.0.0.0").strip()
    mcp.settings.host = host
    mcp.settings.port = _int_env("ANSIBLE_FLOW_HTTP_PORT", 8789)


def build_http_app() -> Any:
    """Starlette app: / and /health open, /mcp bearer-only."""
    global _APP
    if _APP is not None:
        return _APP
    from ansible_flow_mcp.server import mcp

    _install_public_routes()
    configure_http_security()
    app = mcp.streamable_http_app()
    app.add_middleware(BearerGuard)
    _APP = app
    return app


class BearerGuard:
    """Reject /mcp unless the operator bearer matches. Health stays open."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path != MCP_PATH and not path.startswith(MCP_PATH + "/"):
            await self.app(scope, receive, send)
            return

        from ansible_flow_mcp.stdout_audit import (
            actor_from_token,
            actor_var,
            client_ip_var,
            emit_audit,
            request_id_var,
        )

        started = time.perf_counter()
        headers = _header_map(scope)
        request_id = _request_id(headers)
        client_ip = _peer_ip(scope, headers)
        # Legacy jsonl field. The stdout actor is the key id, not this header.
        client_id = _client_id(headers.get("x-ansible-flow-client"))
        req_token = request_id_var.set(request_id)
        ip_token = client_ip_var.set(client_ip)
        actor_token = actor_var.set("anonymous")

        async def send_with_id(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                out = list(message.get("headers") or [])
                if not any(key.lower() == b"x-request-id" for key, _value in out):
                    out.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": out}
            await send(message)

        def _elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        try:
            if not host_allowed(headers.get("host")):
                await _send_json(send_with_id, 421, {"ok": False, "error": "invalid_host"})
                return
            if not rate_limit_allows():
                await _send_json(send_with_id, 429, {"ok": False, "error": "rate_limited"})
                return
            try:
                expected = load_mcp_bearer_token()
            except McpAuthConfigError:
                expected = ""
            if not bearer_matches(headers.get("authorization"), expected):
                _audit_denied(client_id)
                emit_audit(
                    event="mcp_http",
                    actor="anonymous",
                    client_ip=client_ip,
                    request_id=request_id,
                    tool="mcp",
                    outcome="denied",
                    duration_ms=_elapsed(),
                )
                await _send_json(
                    send_with_id,
                    401,
                    {"ok": False, "error": "unauthorized"},
                    extra_headers=[(b"www-authenticate", b'Bearer realm="ansible-flow-mcp"')],
                )
                return
            actor_var.set(actor_from_token(expected))
            _audit_session(headers, client_id)
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(req_token)
            client_ip_var.reset(ip_token)
            actor_var.reset(actor_token)


def _header_map(scope: Scope) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in scope.get("headers") or []:
        out[key.decode("latin-1").lower()] = value.decode("latin-1")
    return out


async def _send_json(
    send: Send,
    status: int,
    payload: dict[str, Any],
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _serve_bound(app: Any, port: int, addresses: list[str]) -> None:
    """One process, one socket per address. Does not listen on every interface."""
    import socket

    import uvicorn

    sockets: list[socket.socket] = []
    try:
        for addr in addresses:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((addr, port))
            sockets.append(sock)
    except OSError:
        for sock in sockets:
            sock.close()
        raise
    shown = ", ".join(f"{addr}:{port}" for addr in addresses)
    sys.stderr.write(
        f"ansible-flow-mcp streamable HTTP on {shown}{MCP_PATH} (bearer required); health at /health\n"
    )
    config = uvicorn.Config(app, log_level="info", proxy_headers=False, access_log=True)
    uvicorn.Server(config).run(sockets=sockets)


def serve_http(*, host: str = "0.0.0.0", port: int = 8789) -> None:
    """Listen for health and authenticated MCP. Exits if no bearer is configured."""
    # Callers have passed socket.INADDR_ANY (an int). The environment stores text.
    if isinstance(host, int):
        host = "0.0.0.0" if host == 0 else str(host)
    else:
        host = str(host)
    os.environ["ANSIBLE_FLOW_HTTP_PORT"] = str(port)
    os.environ["ANSIBLE_FLOW_HTTP_HOST"] = host
    role = (os.environ.get("ANSIBLE_FLOW_ROLE") or "").strip().lower()
    if role == "spoke":
        sys.stderr.write("refusing HTTP MCP on a spoke; agents attach to the hub only\n")
        raise SystemExit(1)
    try:
        load_mcp_bearer_token()
    except McpAuthConfigError as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(1) from exc

    from ansible_flow_mcp.server import activate_role

    activate_role(role="hub" if role == "hub" else None)
    app = build_http_app()
    subnets = (os.environ.get("ANSIBLE_FLOW_HTTP_BIND_SUBNETS") or "").strip()
    if subnets:
        try:
            addresses = listen_hosts(subnets, local_ipv4s())
        except ValueError as exc:
            sys.stderr.write(str(exc) + "\n")
            raise SystemExit(1) from exc
        if addresses == ["127.0.0.1"]:
            sys.stderr.write(
                "warning: ANSIBLE_FLOW_HTTP_BIND_SUBNETS matched no local address; MCP is on loopback only\n"
            )
        _serve_bound(app, port, addresses)
        return
    import uvicorn

    sys.stderr.write(
        f"ansible-flow-mcp streamable HTTP on http://{host}:{port}{MCP_PATH} (bearer required); "
        f"health at /health\n"
    )
    uvicorn.run(app, host=host, port=port, log_level="info", proxy_headers=False, access_log=True)
