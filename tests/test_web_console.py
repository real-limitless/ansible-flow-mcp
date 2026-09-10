from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from ansible_flow_mcp.hub.state import hub_init
from ansible_flow_mcp.web.app import create_app


def test_setup_login_status_and_invite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "hub"
    monkeypatch.setenv("ANSIBLE_FLOW_HUB_DIR", str(root))
    hub_init(name="hub-01", root=root)
    client = TestClient(create_app(root))

    denied = client.get("/api/status")
    assert denied.status_code == 401

    st = client.get("/api/auth/status")
    assert st.status_code == 200
    assert st.json()["setupRequired"] is True

    setup = client.post(
        "/api/auth/setup",
        json={"email": "ops@example.com", "password": "password12"},
    )
    assert setup.status_code == 201
    csrf = setup.json()["csrf"]

    again = client.post(
        "/api/auth/setup",
        json={"email": "other@example.com", "password": "password12"},
    )
    assert again.status_code == 409

    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["initialized"] is True

    invite = client.post(
        "/api/invite",
        json={"name": "spoke-01", "ttl": "15m"},
        headers={"X-CSRF-Token": csrf},
    )
    assert invite.status_code == 200
    body = invite.json()
    assert "spoke" in body["join_command"]
    assert "join" in body["join_command"]
    assert body["token"]

    bad_csrf = client.post(
        "/api/invite",
        json={"name": "spoke-02"},
        headers={"X-CSRF-Token": "nope"},
    )
    assert bad_csrf.status_code == 403

    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert "Sign in" in login_page.text
