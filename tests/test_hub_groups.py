from __future__ import annotations

from pathlib import Path

import pytest

from ansible_flow_mcp.hub.enroll import (
    create_group_op,
    delete_group_op,
    hub_status,
    set_group_members_op,
    update_node,
)
from ansible_flow_mcp.hub.inventory import (
    add_spoke,
    create_group,
    delete_group,
    list_groups,
    load_inventory,
    set_group_members,
    update_spoke,
    write_inventory,
)
from ansible_flow_mcp.hub.state import hub_init
from ansible_flow_mcp.policy import Role, assert_hosts_allowed, load_inventory_groups
from ansible_flow_mcp.tui import (
    App,
    build_spoke_join_command,
    default_join_hub,
    do_invite,
    wrap_text,
    write_opencode_hub_config,
)


@pytest.fixture()
def hub_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "hub"
    monkeypatch.setenv("ANSIBLE_FLOW_HUB_DIR", str(root))
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    hub_init(name="hub-01", root=root)
    # seed two spokes without full join
    inv = load_inventory(root / "inventory.yml")
    add_spoke(inv, name="web-01", ansible_host="10.0.0.1")
    add_spoke(inv, name="db-01", ansible_host="10.0.0.2")
    write_inventory(root / "inventory.yml", inv)
    return root


def test_groups_crud(hub_root: Path):
    inv = load_inventory(hub_root / "inventory.yml")
    create_group(inv, "web")
    set_group_members(inv, "web", ["web-01"])
    assert list_groups(inv) == [{"name": "web", "hosts": ["web-01"]}]
    with pytest.raises(ValueError, match="not an enrolled"):
        set_group_members(inv, "web", ["not-real"])
    with pytest.raises(ValueError, match="reserved"):
        create_group(inv, "spokes")
    assert delete_group(inv, "web") is True


def test_update_spoke(hub_root: Path):
    inv = load_inventory(hub_root / "inventory.yml")
    n = update_spoke(inv, "web-01", ansible_host="10.9.9.9", ansible_port=2222)
    assert n["ansible_host"] == "10.9.9.9"
    assert n["ansible_port"] == 2222


def test_enroll_ops(hub_root: Path):
    create_group_op("prod", root=hub_root)
    set_group_members_op("prod", ["web-01", "db-01"], root=hub_root)
    st = hub_status(root=hub_root)
    assert any(g["name"] == "prod" for g in st["groups"])
    assert len(st["nodes"]) == 2
    update_node("web-01", ansible_user="mcp-spoke", root=hub_root)
    delete_group_op("prod", root=hub_root)


def test_policy_allows_custom_group(hub_root: Path):
    create_group_op("web", root=hub_root)
    set_group_members_op("web", ["web-01"], root=hub_root)
    groups = load_inventory_groups(hub_root / "inventory.yml")
    assert "web" in groups
    assert (
        assert_hosts_allowed(
            "web",
            enrolled={"hub-01", "web-01", "db-01"},
            role=Role.HUB,
            groups=groups,
        )
        == "web"
    )


def test_opencode_config_write(hub_root: Path):
    app = App(hub_root=hub_root, hub_ok=True)
    path = write_opencode_hub_config(app)
    assert path.is_file()
    data = path.read_text(encoding="utf-8")
    assert "ansible-flow-hub" in data
    assert "hub" in data and "session" in data


def test_build_spoke_join_command_quotes_token():
    cmd = build_spoke_join_command(
        token="abc.def+ghi",
        hub="mcp-join@hub.example:22",
        name="web-03",
        public_addr="web-03.example.com",
    )
    assert cmd.startswith("ansible-flow-mcp spoke join")
    assert "--token abc.def+ghi" in cmd or "--token 'abc.def+ghi'" in cmd
    assert "mcp-join@hub.example:22" in cmd
    assert "web-03.example.com" in cmd
    assert "--name web-03" in cmd


def test_wrap_text_breaks_long_lines():
    lines = wrap_text("a" * 50, 20)
    assert all(len(x) <= 20 for x in lines)
    assert "".join(lines) == "a" * 50


def test_do_invite_builds_join_command(hub_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANSIBLE_FLOW_JOIN_HUB", raising=False)
    app = App(hub_root=hub_root, hub_ok=True)
    do_invite(
        app,
        "edge-01",
        "15m",
        hub="mcp-join@ctrl.example",
        public_addr="10.0.0.9",
    )
    assert app.modal == "token"
    assert app.last_token
    assert "spoke join" in app.last_join_cmd
    assert app.last_token in app.last_join_cmd
    assert "mcp-join@ctrl.example" in app.last_join_cmd
    assert "10.0.0.9" in app.last_join_cmd
    assert any("Copy and run" in line for line in app.last_join_lines)


def test_default_join_hub_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANSIBLE_FLOW_JOIN_HUB", "mcp-join@bastion.internal:2222")
    assert default_join_hub() == "mcp-join@bastion.internal:2222"
