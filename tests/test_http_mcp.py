"""Bearer gate for streamable HTTP MCP. Unauthenticated /mcp must fail closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from ansible_flow_mcp.http_mcp import (
    McpAuthConfigError,
    bearer_matches,
    build_http_app,
    host_allowed,
    load_mcp_bearer_token,
    serve_http,
)

TOKEN = "test-operator-bearer-not-a-join-token"
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "ansible-flow-test", "version": "0"},
    },
}


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    hub = tmp_path_factory.mktemp("hub")
    from ansible_flow_mcp.hub.state import hub_init

    hub_init(name="http-test", root=hub)
    monkey = pytest.MonkeyPatch()
    monkey.setenv("ANSIBLE_FLOW_HUB_DIR", str(hub))
    monkey.setenv("ANSIBLE_FLOW_ROLE", "hub")
    monkey.setenv("ANSIBLE_FLOW_MCP_TOKEN", TOKEN)
    monkey.setenv("ANSIBLE_FLOW_MCP_RATE_PER_MINUTE", "120")
    monkey.delenv("ANSIBLE_FLOW_MCP_TOKEN_FILE", raising=False)
    app = build_http_app()
    with TestClient(app) as http:
        yield http
    monkey.undo()


def _mcp_headers(**extra: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **extra,
    }
    return headers


def test_bearer_match_rejects_missing_and_wrong_scheme():
    assert bearer_matches(None, TOKEN) is False
    assert bearer_matches("", TOKEN) is False
    assert bearer_matches("Basic abc", TOKEN) is False
    assert bearer_matches("Bearer", TOKEN) is False
    assert bearer_matches("Bearer nope", TOKEN) is False
    assert bearer_matches("Bearer " + TOKEN + " ", TOKEN) is True
    assert bearer_matches("bearer " + TOKEN, TOKEN) is True
    assert bearer_matches(None, "") is False


def test_load_token_refuses_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("ANSIBLE_FLOW_MCP_TOKEN", raising=False)
    monkeypatch.delenv("ANSIBLE_FLOW_MCP_TOKEN_FILE", raising=False)
    with pytest.raises(McpAuthConfigError):
        load_mcp_bearer_token()
    empty = tmp_path / "empty"
    empty.write_text("\n", encoding="utf-8")
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_TOKEN_FILE", str(empty))
    with pytest.raises(McpAuthConfigError):
        load_mcp_bearer_token()
    secret = tmp_path / "secret"
    secret.write_text(TOKEN + "\n", encoding="utf-8")
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_TOKEN_FILE", str(secret))
    assert load_mcp_bearer_token() == TOKEN
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_TOKEN", "from-env")
    assert load_mcp_bearer_token() == "from-env"


def test_serve_refuses_without_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANSIBLE_FLOW_MCP_TOKEN", raising=False)
    monkeypatch.delenv("ANSIBLE_FLOW_MCP_TOKEN_FILE", raising=False)
    monkeypatch.delenv("ANSIBLE_FLOW_ROLE", raising=False)
    with pytest.raises(SystemExit) as exc:
        serve_http(host="127.0.0.1", port=9)
    assert exc.value.code == 1


def test_serve_refuses_spoke(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_TOKEN", TOKEN)
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "spoke")
    with pytest.raises(SystemExit):
        serve_http(host="127.0.0.1", port=9)


def test_serve_invokes_uvicorn_when_token_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_TOKEN", TOKEN)
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    called: dict[str, object] = {}

    def fake_run(app, **kwargs):  # type: ignore[no-untyped-def]
        called["app"] = app
        called["host"] = kwargs.get("host")
        called["port"] = kwargs.get("port")

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    serve_http(host="127.0.0.1", port=8789)
    assert called["host"] == "127.0.0.1"
    assert called["port"] == 8789
    assert called["app"] is not None


def test_health_is_open_and_hides_token(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["mcp"]["path"] == "/mcp"
    assert body["mcp"]["auth"] == "bearer"
    blob = response.text
    assert TOKEN not in blob
    root = client.get("/")
    assert root.status_code == 200
    assert TOKEN not in root.text


def test_mcp_rejects_unauthenticated(client: TestClient):
    missing = client.post("/mcp", headers=_mcp_headers(), json=INIT)
    assert missing.status_code == 401
    assert missing.json()["error"] == "unauthorized"
    assert missing.headers["www-authenticate"].lower().startswith("bearer")
    assert TOKEN not in missing.text

    wrong = client.post(
        "/mcp",
        headers=_mcp_headers(Authorization="Bearer wrong-token"),
        json=INIT,
    )
    assert wrong.status_code == 401
    assert TOKEN not in wrong.text

    basic = client.post(
        "/mcp",
        headers=_mcp_headers(Authorization="Basic dXNlcjpwYXNz"),
        json=INIT,
    )
    assert basic.status_code == 401


def test_mcp_accepts_bearer_initialize(client: TestClient):
    response = client.post(
        "/mcp",
        headers=_mcp_headers(
            Authorization=f"Bearer {TOKEN}",
            **{"X-Ansible-Flow-Client": "ci-bot"},
        ),
        json=INIT,
    )
    assert response.status_code == 200, response.text
    assert TOKEN not in response.text
    assert "protocolVersion" in response.text or "serverInfo" in response.text


def test_audit_records_transport_and_client_without_secret(client: TestClient):
    from ansible_flow_mcp.hub.state import read_audit
    from ansible_flow_mcp.paths import hub_dir

    response = client.post(
        "/mcp",
        headers=_mcp_headers(
            Authorization=f"Bearer {TOKEN}",
            **{"X-Ansible-Flow-Client": "ci-bot"},
        ),
        json=INIT,
    )
    assert response.status_code == 200
    events = read_audit(root=hub_dir(), limit=50)
    matched = [
        event
        for event in events
        if event.get("event") == "mcp_http_session" and event.get("client_id") == "ci-bot"
    ]
    assert matched, events
    assert matched[0]["transport"] == "http"
    raw = (hub_dir() / "audit.jsonl").read_text(encoding="utf-8")
    assert TOKEN not in raw
    denied = client.post("/mcp", headers=_mcp_headers(), json=INIT)
    assert denied.status_code == 401
    denied_events = [
        event for event in read_audit(root=hub_dir(), limit=20) if event.get("event") == "mcp_http_denied"
    ]
    assert denied_events
    assert denied_events[0]["transport"] == "http"


def test_bad_host_rejected(client: TestClient):
    response = client.post(
        "/mcp",
        headers=_mcp_headers(Authorization=f"Bearer {TOKEN}", Host="evil.example"),
        json=INIT,
    )
    assert response.status_code == 421


def test_host_allowlist_includes_public_name():
    assert host_allowed("ansible-flow-mcp.z.srl") or host_allowed(
        "ansible-flow-mcp.z.srl",
        ["ansible-flow-mcp.z.srl", "ansible-flow-mcp.z.srl:*", "127.0.0.1:*"],
    )
    assert host_allowed("127.0.0.1:8789", ["127.0.0.1:*"]) is True
    assert host_allowed("evil.example", ["127.0.0.1:*", "ansible-flow-mcp.z.srl"]) is False


def test_rate_limit(monkeypatch: pytest.MonkeyPatch, client: TestClient):
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_RATE_PER_MINUTE", "1")
    from ansible_flow_mcp import http_mcp

    with http_mcp._RATE_LOCK:
        http_mcp._RATE_HITS.clear()
    first = client.post("/mcp", headers=_mcp_headers(), json=INIT)
    second = client.post("/mcp", headers=_mcp_headers(), json=INIT)
    assert first.status_code == 401
    assert second.status_code == 429
    monkeypatch.setenv("ANSIBLE_FLOW_MCP_RATE_PER_MINUTE", "120")
    with http_mcp._RATE_LOCK:
        http_mcp._RATE_HITS.clear()


def test_stdio_run_does_not_require_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANSIBLE_FLOW_MCP_TOKEN", raising=False)
    from ansible_flow_mcp import server

    called: dict[str, str] = {}

    def fake_run(*, transport: str = "stdio") -> None:
        called["transport"] = transport

    monkeypatch.setattr(server.mcp, "run", fake_run)
    server.run_server(role=None)
    assert called["transport"] == "stdio"


def test_activate_role_registers_hub_tools_once(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    from ansible_flow_mcp import server

    server.activate_role(role="hub")
    names = {tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert "list_nodes" in names
    assert "run_module" in names
    server.activate_role(role="hub")
    again = [tool.name for tool in server.mcp._tool_manager.list_tools()]
    assert again.count("list_nodes") == 1
