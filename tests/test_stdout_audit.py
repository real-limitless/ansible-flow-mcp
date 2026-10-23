from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from ansible_flow_mcp.http_mcp import BearerGuard, listen_hosts, load_mcp_bearer_token
from ansible_flow_mcp.stdout_audit import actor_from_token, emit_audit


def test_emit_audit_shape_and_redaction(capsys: pytest.CaptureFixture[str]):
    emit_audit(
        event="tool_call",
        actor="key:abc",
        client_ip="192.0.2.10",
        request_id="req-1",
        tool="run_module",
        outcome="ok",
        duration_ms=4,
        target="web",
        args={"password": "nope"},
        token="nope",
    )
    text = capsys.readouterr().out
    record = json.loads(text.strip())
    assert record["ts"].endswith("Z")
    assert record["event"] == "tool_call"
    assert record["actor"] == "key:abc"
    assert record["client_ip"] == "192.0.2.10"
    assert record["request_id"] == "req-1"
    assert record["tool"] == "run_module"
    assert record["outcome"] == "ok"
    assert record["duration_ms"] == 4
    assert record["target"] == "web"
    assert "args" not in record
    assert "token" not in record
    assert "nope" not in text


def test_actor_is_a_stable_key_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANSIBLE_FLOW_MCP_KEY_LABEL", raising=False)
    first = actor_from_token("file-bearer")
    assert first == actor_from_token("file-bearer")
    assert first.startswith("key:")
    assert "file-bearer" not in first
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_KEY_LABEL", "gateway/lab")
    assert actor_from_token("file-bearer") == "label:gatewaylab"


def test_token_file_is_reread(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("ANSIBLE_FLOW_MCP_TOKEN", raising=False)
    path = tmp_path / "mcp.http.token"
    path.write_text("first-token\n", encoding="utf-8")
    os.chmod(path, 0o400)
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_TOKEN_FILE", str(path))
    assert load_mcp_bearer_token() == "first-token"
    os.chmod(path, 0o600)
    path.write_text("second-token\n", encoding="utf-8")
    os.chmod(path, 0o400)
    assert load_mcp_bearer_token() == "second-token"


def test_request_uses_peer_and_key_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    token = "file-bearer-not-logged"
    path = tmp_path / "mcp.http.token"
    path.write_text(token + "\n", encoding="utf-8")
    monkeypatch.delenv("ANSIBLE_FLOW_MCP_TOKEN", raising=False)
    monkeypatch.delenv("ANSIBLE_FLOW_TRUST_PROXY", raising=False)
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_TOKEN_FILE", str(path))
    seen: dict[str, str] = {}

    async def downstream(scope, receive, send):
        from ansible_flow_mcp.stdout_audit import actor_var, client_ip_var, request_id_var

        seen["actor"] = actor_var.get()
        seen["ip"] = client_ip_var.get()
        seen["req"] = request_id_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    guard = BearerGuard(downstream)

    async def once(extra: list[tuple[bytes, bytes]] | None = None):
        messages: list[dict] = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        headers = [
            (b"authorization", f"Bearer {token}".encode()),
            (b"host", b"localhost"),
            (b"x-request-id", b"req-1"),
            (b"x-ansible-flow-client", b"spoofed"),
            (b"x-forwarded-for", b"198.51.100.8"),
        ]
        if extra:
            headers.extend(extra)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": headers,
            "client": ("192.0.2.10", 40000),
        }
        await guard(scope, receive, send)
        return messages

    messages = asyncio.run(once())
    echoed = {key.decode(): value.decode() for key, value in messages[0]["headers"]}
    assert echoed["x-request-id"] == "req-1"
    assert seen["req"] == "req-1"
    assert seen["ip"] == "192.0.2.10"
    assert seen["actor"] == actor_from_token(token)
    assert "spoofed" not in seen["actor"]
    assert token not in seen["actor"]

    monkeypatch.setenv("ANSIBLE_FLOW_TRUST_PROXY", "1")
    asyncio.run(once())
    assert seen["ip"] == "198.51.100.8"


def test_listen_hosts_skips_egress_addresses():
    chosen = listen_hosts(
        "192.0.2.0/24,198.51.100.0/24",
        ["127.0.0.1", "192.0.2.10", "198.51.100.8", "203.0.113.5"],
    )
    assert chosen == ["127.0.0.1", "192.0.2.10", "198.51.100.8"]
    with pytest.raises(ValueError):
        listen_hosts("not-a-cidr", [])


def test_serve_binds_only_allowed_subnets(monkeypatch: pytest.MonkeyPatch):
    import ansible_flow_mcp.http_mcp as http_mcp

    monkeypatch.setenv("ANSIBLE_FLOW_MCP_TOKEN", "file-bearer")
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    monkeypatch.setenv("ANSIBLE_FLOW_HTTP_BIND_SUBNETS", "192.0.2.0/24")
    monkeypatch.setattr(http_mcp, "local_ipv4s", lambda: ["192.0.2.10", "203.0.113.5"])
    seen: dict[str, object] = {}

    def fake_bound(_app: object, port: int, addresses: list[str]) -> None:
        seen["port"] = port
        seen["addresses"] = addresses

    monkeypatch.setattr(http_mcp, "_serve_bound", fake_bound)
    http_mcp.serve_http(host="0.0.0.0", port=8790)
    assert seen["addresses"] == ["127.0.0.1", "192.0.2.10"]
    assert seen["port"] == 8790


def test_run_module_audit_omits_args(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    class Result:
        exit_code = 0

        def to_dict(self) -> dict[str, str]:
            return {"stdout": "", "stderr": "", "exitCode": 0}

    def fake_run(*_args, **kwargs):
        assert kwargs["args"]["password"] == "s3cret"
        return Result()

    monkeypatch.setattr("ansible_flow_mcp.server.run_module", fake_run)
    from ansible_flow_mcp.server import run_module_tool

    body = run_module_tool(module="ansible.builtin.ping", args={"password": "s3cret"}, hosts="web")
    assert "s3cret" not in body
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["event"] == "tool_call"
    assert record["tool"] == "run_module"
    assert record["target"] == "web"
    assert record["outcome"] == "ok"
    assert "s3cret" not in json.dumps(record)


def test_run_module_denied(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    def fake_run(*_args, **_kwargs):
        raise ValueError("spoke mode allows hosts=localhost only")

    monkeypatch.setattr("ansible_flow_mcp.server.run_module", fake_run)
    from ansible_flow_mcp.server import run_module_tool

    with pytest.raises(ValueError):
        run_module_tool(module="ansible.builtin.ping", hosts="other")
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["tool"] == "run_module"
    assert record["outcome"] == "denied"
    assert record["target"] == "other"
