from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import pytest

from ansible_flow_mcp.access_log import log_access
from ansible_flow_mcp.cli import read_supplied_token
from ansible_flow_mcp.http_mcp import (
    BearerAuthMiddleware,
    ensure_mcp_http_token,
    key_prefix,
    load_mcp_http_token,
    resolve_bind,
)


def test_unspecified_bind_uses_any_address():
    assert resolve_bind("unspecified") == socket.INADDR_ANY
    assert resolve_bind("localhost") == "localhost"
    assert resolve_bind(None) == "localhost"


def test_mcp_token_file_mode_and_stability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANSIBLE_FLOW_MCP_TOKEN_FILE", raising=False)
    root = tmp_path / "hub"
    path = ensure_mcp_http_token(root)
    assert path.name == "mcp.http.token"
    assert path.stat().st_mode & 0o777 == 0o400
    first = load_mcp_http_token(root)
    assert first
    assert load_mcp_http_token(root) == first
    assert "\n" not in first


def test_mcp_token_file_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dest = tmp_path / "nested" / "bearer"
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_TOKEN_FILE", str(dest))
    path = ensure_mcp_http_token(tmp_path / "ignored")
    assert path == dest
    assert dest.stat().st_mode & 0o777 == 0o400


def test_log_access_rejects_secret_fields(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(ValueError):
        log_access(action="mcp.http", outcome="ok", token="nope")
    log_access(
        action="mcp.http",
        outcome="ok",
        actor="bearer:abcd",
        source_ip="192.0.2.10",
        request_id="req-1",
        method="POST",
    )
    line = capsys.readouterr().out.strip()
    record = json.loads(line)
    assert record["service"] == "ansible-flow-mcp"
    assert record["ts"].endswith("Z")
    assert record["request_id"] == "req-1"
    assert record["source_ip"] == "192.0.2.10"
    assert "nope" not in line


def test_bearer_middleware(capsys: pytest.CaptureFixture[str]):
    token = "test-token-value-not-a-secret-file"

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def call(headers, path="/mcp"):
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": headers,
            "client": ("192.0.2.10", 40000),
        }
        await BearerAuthMiddleware(app, token=token)(scope, receive, send)
        return messages

    denied = asyncio.run(call([]))
    assert denied[0]["status"] == 401
    allowed = asyncio.run(
        call([(b"authorization", f"Bearer {token}".encode())])
    )
    assert allowed[0]["status"] == 200
    missing = asyncio.run(call([], path="/debug"))
    assert missing[0]["status"] == 404
    text = capsys.readouterr().out
    assert token not in text
    assert key_prefix(token) in text
    assert "192.0.2.10" in text


def test_read_supplied_token(tmp_path: Path):
    path = tmp_path / "join.token"
    path.write_text("one-time\n", encoding="utf-8")
    assert read_supplied_token(token=None, token_file=str(path)) == "one-time"
    assert read_supplied_token(token="abc", token_file=None) == "abc"
    with pytest.raises(ValueError):
        read_supplied_token(token="abc", token_file=str(path))
    with pytest.raises(ValueError):
        read_supplied_token(token=None, token_file=None)
