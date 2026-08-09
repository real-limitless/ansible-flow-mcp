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
from ansible_flow_mcp.tui import write_opencode_hub_config
from ansible_flow_mcp.tui import App


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
