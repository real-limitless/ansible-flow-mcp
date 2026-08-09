from __future__ import annotations

import os
from pathlib import Path

import pytest

from ansible_flow_mcp.hub.enroll import accept_join, hub_status, revoke_node
from ansible_flow_mcp.hub.inventory import list_spoke_names, load_inventory
from ansible_flow_mcp.hub.state import hub_init, load_hub_state
from ansible_flow_mcp.hub.tokens import issue_token, verify_token
from ansible_flow_mcp.policy import Role, assert_hosts_allowed
from ansible_flow_mcp.runner import run_module
from ansible_flow_mcp.security import SecurityPolicy
from ansible_flow_mcp.spoke.join import spoke_join, spoke_status


@pytest.fixture()
def hub_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "hub"
    monkeypatch.setenv("ANSIBLE_FLOW_HUB_DIR", str(root))
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    hub_init(name="hub-01", root=root)
    return root


@pytest.fixture()
def spoke_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "spoke"
    monkeypatch.setenv("ANSIBLE_FLOW_SPOKE_DIR", str(root))
    return root


def test_hub_init_and_status(hub_root: Path):
    st = load_hub_state(hub_root)
    assert st.name == "hub-01"
    assert (hub_root / "inventory.yml").is_file()
    assert (hub_root / "keys" / "hub_client").is_file()
    status = hub_status(state=st)
    assert status["spokes"] == []
    assert status["hub_id"] == st.hub_id


def test_token_roundtrip_and_replay(hub_root: Path):
    st = load_hub_state(hub_root)
    issued = issue_token("web-03", ttl_seconds=600, state=st)
    assert issued.node_name == "web-03"
    claims = verify_token(issued.token, state=st, consume=True)
    assert claims.node_name == "web-03"
    with pytest.raises(ValueError, match="replay"):
        verify_token(issued.token, state=st, consume=True)


def test_token_expiry(hub_root: Path):
    st = load_hub_state(hub_root)
    issued = issue_token("x", ttl_seconds=60, state=st)
    # forge expired by verifying after mutating time — issue short and rewind exp via raw
    import time

    bad = issue_token("y", ttl_seconds=60, state=st)
    # consume with monkeypatched time past exp
    real = time.time
    try:
        time.time = lambda: real() + 10_000  # type: ignore[assignment]
        with pytest.raises(ValueError, match="expired"):
            verify_token(bad.token, state=st, consume=True)
    finally:
        time.time = real  # type: ignore[assignment]


def test_join_enrolls_spoke(hub_root: Path, spoke_root: Path, tmp_path: Path):
    st = load_hub_state(hub_root)
    issued = issue_token("spoke-02", ttl_seconds=900, state=st)
    ak = tmp_path / "authorized_keys"

    def transport(_hub: str, body: dict):
        from ansible_flow_mcp.hub.enroll import JoinRequest, accept_join

        resp = accept_join(JoinRequest.from_dict(body), state=st)
        return resp.to_dict()

    result = spoke_join(
        token=issued.token,
        hub="mcp-join@hub-01",
        public_addr="spoke-02",
        root=spoke_root,
        transport=transport,
        auth_keys_path=ak,
    )
    assert result["ok"] is True
    assert "spoke-02" in list_spoke_names(load_inventory(st.inventory_path))
    inv = load_inventory(st.inventory_path)
    spoke = inv["all"]["children"]["spokes"]["hosts"]["spoke-02"]
    assert spoke.get("ansible_user") == "mcp-ansible"
    assert ak.is_file()
    text = ak.read_text(encoding="utf-8")
    assert "command=" in text
    assert "spoke session" in text
    # ansible key must be plain (no ForceCommand) on separate authorized_keys
    ansible_ak = Path(result["ansible_authorized_keys"])
    assert ansible_ak.is_file()
    atext = ansible_ak.read_text(encoding="utf-8")
    assert "command=" not in atext
    assert "ssh-" in atext
    assert spoke_status(root=spoke_root)["enrolled"] is True


def test_revoke_removes_spoke(hub_root: Path):
    st = load_hub_state(hub_root)
    issued = issue_token("spoke-09", state=st)
    from ansible_flow_mcp.hub.enroll import JoinRequest

    accept_join(
        JoinRequest(token=issued.token, node_name="spoke-09", public_addr="10.0.0.9"),
        state=st,
    )
    assert "spoke-09" in hub_status(state=st)["spokes"]
    revoke_node("spoke-09", state=st)
    assert "spoke-09" not in hub_status(state=st)["spokes"]


def test_policy_spoke_localhost_only():
    with pytest.raises(ValueError, match="localhost"):
        assert_hosts_allowed("web-01", enrolled=set(), role=Role.SPOKE)
    assert assert_hosts_allowed("localhost", enrolled=set(), role=Role.SPOKE) == "localhost"


def test_policy_hub_rejects_unenrolled(hub_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANSIBLE_FLOW_HUB_DIR", str(hub_root))
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    with pytest.raises(ValueError, match="not enrolled"):
        assert_hosts_allowed(
            "evil-host",
            enrolled={"hub-01", "spoke-02"},
            role=Role.HUB,
        )
    assert (
        assert_hosts_allowed("spoke-02", enrolled={"hub-01", "spoke-02"}, role=Role.HUB)
        == "spoke-02"
    )


def test_runner_hub_rejects_unenrolled_host(hub_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANSIBLE_FLOW_HUB_DIR", str(hub_root))
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    pol = SecurityPolicy(collections={"ansible.builtin"}, deny_modules=set())

    def fake_run(argv, env, timeout):
        return 0, "", ""

    with pytest.raises(ValueError, match="not enrolled"):
        run_module(
            "ansible.builtin.ping",
            hosts="not-a-spoke",
            check_mode=True,
            policy=pol,
            run_fn=fake_run,
        )


def test_runner_hub_rejects_client_inventory(hub_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("ANSIBLE_FLOW_HUB_DIR", str(hub_root))
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    pol = SecurityPolicy(collections={"ansible.builtin"}, deny_modules=set())
    evil = tmp_path / "evil.ini"
    evil.write_text("all\n", encoding="utf-8")

    with pytest.raises(ValueError, match="client-supplied inventory"):
        run_module(
            "ansible.builtin.ping",
            hosts="localhost",
            inventory=str(evil),
            check_mode=True,
            policy=pol,
            run_fn=lambda *a, **k: (0, "", ""),
        )


def test_runner_require_check(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANSIBLE_FLOW_ROLE", raising=False)
    monkeypatch.delenv("ANSIBLE_FLOW_HUB_DIR", raising=False)
    monkeypatch.setenv("ANSIBLE_FLOW_REQUIRE_CHECK", "1")
    pol = SecurityPolicy(collections={"ansible.builtin"}, deny_modules=set())
    with pytest.raises(ValueError, match="check_mode"):
        run_module(
            "ansible.builtin.ping",
            check_mode=False,
            policy=pol,
            run_fn=lambda *a, **k: (0, "", ""),
        )


def test_default_hub_dir_falls_back_when_prod_unwritable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from ansible_flow_mcp import paths as paths_mod

    monkeypatch.delenv("ANSIBLE_FLOW_HUB_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    monkeypatch.setattr(paths_mod, "PROD_HUB_DIR", blocked / "ansible-flow" / "hub")
    try:
        d = paths_mod.default_hub_dir()
        assert d == tmp_path / "xdg" / "ansible-flow" / "hub"
        assert paths_mod.hub_dir() == d.resolve()
    finally:
        blocked.chmod(0o700)
