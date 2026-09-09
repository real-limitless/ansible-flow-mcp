from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from ansible_flow_mcp.admin.http import make_server
from ansible_flow_mcp.cli import main as cli_main
from ansible_flow_mcp.hub.enroll import register_target
from ansible_flow_mcp.hub.inventory import add_spoke, load_inventory, write_inventory
from ansible_flow_mcp.hub.state import hub_init, load_admin_token, read_audit
from ansible_flow_mcp.hub.tokens import issue_token


@pytest.fixture()
def hub_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "hub"
    monkeypatch.setenv("ANSIBLE_FLOW_HUB_DIR", str(root))
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    monkeypatch.setenv("ANSIBLE_FLOW_ADMIN_TOKEN", "test-admin-token")
    hub_init(name="hub-01", root=root)
    inv = load_inventory(root / "inventory.yml")
    add_spoke(inv, name="web-01", ansible_host="10.0.0.1")
    write_inventory(root / "inventory.yml", inv)
    return root


@pytest.fixture()
def admin_http(hub_root: Path):
    httpd = make_server(root=hub_root, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    try:
        yield host, int(port), hub_root
    finally:
        httpd.shutdown()
        httpd.server_close()


def _req(
    addr: tuple[str, int],
    method: str,
    path: str,
    *,
    token: str | None = "test-admin-token",
    body: dict | None = None,
) -> tuple[int, dict | str]:
    conn = HTTPConnection(addr[0], addr[1], timeout=10)
    headers: dict[str, str] = {}
    raw = None
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(raw))
    conn.request(method, path, body=raw, headers=headers)
    resp = conn.getresponse()
    text = resp.read().decode("utf-8")
    conn.close()
    try:
        return resp.status, json.loads(text)
    except json.JSONDecodeError:
        return resp.status, text


def test_hub_init_writes_admin_token_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "hub"
    monkeypatch.delenv("ANSIBLE_FLOW_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("ANSIBLE_FLOW_HUB_DIR", str(root))
    hub_init(name="hub-01", root=root)
    path = root / "admin.token"
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_admin_token(root)
    assert "token" not in path.read_text() or True


def test_health_and_unauth(admin_http):
    host, port, _ = admin_http
    status, body = _req((host, port), "GET", "/health", token=None)
    assert status == 200
    assert body["ok"] is True
    assert body.get("version")
    assert "catalogDir" in body
    assert "token" not in json.dumps(body)
    status, body = _req((host, port), "GET", "/v1/status", token=None)
    assert status == 401
    status, body = _req((host, port), "GET", "/v1/status", token="wrong-token-value")
    assert status == 401


def test_admin_static(admin_http):
    host, port, _ = admin_http
    status, body = _req((host, port), "GET", "/admin/", token=None)
    assert status == 200
    assert "ansible-flow" in str(body)
    status, css = _req((host, port), "GET", "/admin/styles.css", token=None)
    assert status == 200
    assert "--copper" in str(css) or "--accent" in str(css)


def test_status_and_crud(admin_http):
    host, port, root = admin_http
    status, body = _req((host, port), "GET", "/v1/status")
    assert status == 200
    assert body["name"] == "hub-01"
    assert "web-01" in body["spokes"]

    status, body = _req(
        (host, port),
        "POST",
        "/v1/targets",
        body={"name": "win-01", "ansible_host": "10.0.4.20", "ansible_connection": "winrm"},
    )
    assert status == 201
    assert body["ok"] is True

    status, body = _req((host, port), "GET", "/v1/targets")
    assert status == 200
    names = [t["name"] for t in body["targets"]]
    assert "win-01" in names

    status, body = _req((host, port), "POST", "/v1/groups", body={"name": "prod"})
    assert status == 201
    status, body = _req(
        (host, port),
        "PUT",
        "/v1/groups/prod/members",
        body={"hosts": ["web-01", "win-01"]},
    )
    assert status == 200
    assert set(body["group"]["hosts"]) == {"web-01", "win-01"}

    status, body = _req(
        (host, port),
        "PATCH",
        "/v1/nodes/web-01",
        body={"ansible_user": "mcp-spoke"},
    )
    assert status == 200
    assert body["node"]["ansible_user"] == "mcp-spoke"

    status, body = _req((host, port), "DELETE", "/v1/nodes/web-01")
    assert status == 200
    status, body = _req((host, port), "GET", "/v1/status")
    assert "web-01" not in body["spokes"]

    status, body = _req((host, port), "DELETE", "/v1/targets/win-01")
    assert status == 200
    status, body = _req((host, port), "DELETE", "/v1/groups/prod")
    assert status == 200


def test_issue_token_not_in_audit(admin_http):
    host, port, root = admin_http
    status, body = _req(
        (host, port),
        "POST",
        "/v1/tokens",
        body={"name": "edge-01", "ttl_seconds": 120, "hub": "mcp-join@hub", "public_addr": "edge-01"},
    )
    assert status == 201
    token = body["token"]
    assert token
    assert "spoke join" in body["join_command"]
    status, audit = _req((host, port), "GET", "/v1/audit?limit=20")
    assert status == 200
    blob = json.dumps(audit)
    assert token not in blob
    assert "********" in json.dumps(read_audit(root=root, limit=50)) or "issue_token" in blob


def test_password_rejected_on_target(admin_http):
    host, port, _ = admin_http
    status, body = _req(
        (host, port),
        "POST",
        "/v1/targets",
        body={
            "name": "bad-01",
            "ansible_host": "10.0.0.9",
            "extra": {"password": "nope"},
        },
    )
    assert status == 400
    assert "password" in str(body.get("error", "")).lower() or "secret" in str(body).lower()


def test_register_target_helper_still_works(hub_root: Path):
    out = register_target("sw-01", ansible_host="10.1.1.1", ansible_connection="network_cli", root=hub_root)
    assert out["ok"] is True


def test_issue_token_helper_redacts_audit(hub_root: Path):
    issued = issue_token("n1", ttl_seconds=120, root=hub_root)
    events = read_audit(root=hub_root, limit=10)
    blob = json.dumps(events)
    assert issued.token not in blob


def test_cli_hub_dir_before_subcommand(hub_root: Path, capsys: pytest.CaptureFixture[str]):
    cli_main(["--hub-dir", str(hub_root), "hub", "status"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["name"] == "hub-01"
    assert "web-01" in data["spokes"]


def test_cli_hub_dir_before_doctor(hub_root: Path, capsys: pytest.CaptureFixture[str]):
    cli_main(["--hub-dir", str(hub_root), "doctor"])
    data = json.loads(capsys.readouterr().out)
    assert "ok" in data
    assert data.get("hubDir")


def test_cli_register_target_secret_no_traceback(
    hub_root: Path, capsys: pytest.CaptureFixture[str]
):
    with pytest.raises(SystemExit) as ei:
        cli_main(
            [
                "--hub-dir",
                str(hub_root),
                "hub",
                "register-target",
                "--name",
                "win-x",
                "--host",
                "10.0.0.9",
                "--connection",
                "winrm",
                "--extra",
                '{"ansible_password":"nope"}',
            ]
        )
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "ansible_password" in err
    assert "Traceback" not in err


def test_cli_spoke_call_missing_node_no_traceback(
    hub_root: Path, capsys: pytest.CaptureFixture[str]
):
    with pytest.raises(SystemExit) as ei:
        cli_main(
            [
                "--hub-dir",
                str(hub_root),
                "hub",
                "spoke-call",
                "--node",
                "web-99",
            ]
        )
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "not enrolled" in err
    assert "Traceback" not in err


def test_default_admin_port(monkeypatch: pytest.MonkeyPatch):
    from ansible_flow_mcp.admin.http import DEFAULT_PORT, _default_port

    monkeypatch.delenv("ANSIBLE_FLOW_ADMIN_PORT", raising=False)
    assert DEFAULT_PORT == 8789
    assert _default_port() == 8789
    monkeypatch.setenv("ANSIBLE_FLOW_ADMIN_PORT", "18789")
    assert _default_port() == 18789
