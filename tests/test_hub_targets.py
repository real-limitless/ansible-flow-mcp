from __future__ import annotations

from pathlib import Path

import pytest

from ansible_flow_mcp.hub.enroll import (
    create_group_op,
    hub_status,
    register_target,
    remove_target_node,
    set_group_members_op,
    update_target_node,
)
from ansible_flow_mcp.hub.inventory import (
    KIND_TARGET,
    add_spoke,
    add_target,
    create_group,
    get_target,
    list_target_names,
    load_inventory,
    remove_target,
    set_group_members,
    targetable_host_names,
    write_inventory,
)
from ansible_flow_mcp.hub.state import hub_init
from ansible_flow_mcp.policy import Role, assert_hosts_allowed, load_enrolled_hosts, load_inventory_groups
from ansible_flow_mcp.ssh import _spoke_target


@pytest.fixture()
def hub_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "hub"
    monkeypatch.setenv("ANSIBLE_FLOW_HUB_DIR", str(root))
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    hub_init(name="hub-01", root=root)
    inv = load_inventory(root / "inventory.yml")
    add_spoke(inv, name="web-01", ansible_host="10.0.0.1")
    write_inventory(root / "inventory.yml", inv)
    return root


def test_default_inventory_has_targets_group(hub_root: Path):
    inv = load_inventory(hub_root / "inventory.yml")
    assert "targets" in inv["all"]["children"]
    assert inv["all"]["children"]["targets"]["hosts"] == {}


def test_register_winrm_target(hub_root: Path):
    out = register_target(
        "win-01",
        ansible_host="10.0.4.20",
        ansible_connection="winrm",
        ansible_user="Administrator",
        root=hub_root,
    )
    assert out["ok"] is True
    node = out["node"]
    assert node["kind"] == KIND_TARGET
    assert node["ansible_connection"] == "winrm"
    assert node["ansible_port"] == 5986
    assert node["ansible_host"] == "10.0.4.20"
    assert "win-01" in list_target_names(load_inventory(hub_root / "inventory.yml"))


def test_name_collision_spoke_vs_target(hub_root: Path):
    with pytest.raises(ValueError, match="already an enrolled spoke"):
        register_target("web-01", ansible_host="1.2.3.4", root=hub_root)
    register_target("win-01", ansible_host="1.2.3.4", ansible_connection="winrm", root=hub_root)
    inv = load_inventory(hub_root / "inventory.yml")
    with pytest.raises(ValueError, match="already an Ansible target"):
        add_spoke(inv, name="win-01", ansible_host="9.9.9.9")


def test_refuse_inline_secrets(hub_root: Path):
    with pytest.raises(ValueError, match="secret or reserved"):
        register_target(
            "win-sec",
            ansible_host="10.0.0.9",
            ansible_connection="winrm",
            extra={"ansible_password": "nope"},
            root=hub_root,
        )


def test_refuse_unknown_extra_keys(hub_root: Path):
    with pytest.raises(ValueError, match="unsupported target var"):
        register_target(
            "win-x",
            ansible_host="10.0.0.9",
            ansible_connection="winrm",
            extra={"not_a_real_var": 1},
            root=hub_root,
        )


def test_update_and_remove_target(hub_root: Path):
    register_target("win-01", ansible_host="10.0.4.1", ansible_connection="winrm", root=hub_root)
    upd = update_target_node("win-01", ansible_host="10.0.4.2", ansible_port=5985, root=hub_root)
    assert upd["node"]["ansible_host"] == "10.0.4.2"
    assert upd["node"]["ansible_port"] == 5985
    rm = remove_target_node("win-01", root=hub_root)
    assert rm["removed_from_inventory"] is True
    assert "win-01" not in list_target_names(load_inventory(hub_root / "inventory.yml"))


def test_groups_accept_targets(hub_root: Path):
    register_target("win-01", ansible_host="10.0.4.1", ansible_connection="winrm", root=hub_root)
    create_group_op("windows", root=hub_root)
    set_group_members_op("windows", ["win-01", "web-01"], root=hub_root)
    st = hub_status(root=hub_root)
    grp = next(g for g in st["groups"] if g["name"] == "windows")
    assert set(grp["hosts"]) == {"win-01", "web-01"}
    remove_target_node("win-01", root=hub_root)
    st2 = hub_status(root=hub_root)
    grp2 = next(g for g in st2["groups"] if g["name"] == "windows")
    assert "win-01" not in grp2["hosts"]


def test_hub_status_kind_projection(hub_root: Path):
    register_target("win-01", ansible_host="10.0.4.1", ansible_connection="winrm", root=hub_root)
    st = hub_status(root=hub_root)
    assert "win-01" in st["targets"]
    assert "web-01" in st["spokes"]
    kinds = {n["name"]: n["kind"] for n in st["nodes"]}
    assert kinds["web-01"] == "spoke"
    assert kinds["win-01"] == "target"
    # secrets never present
    win = next(n for n in st["nodes"] if n["name"] == "win-01")
    assert "ansible_password" not in win


def test_policy_allows_target_host(hub_root: Path):
    register_target("win-01", ansible_host="10.0.4.1", ansible_connection="winrm", root=hub_root)
    enrolled = load_enrolled_hosts(hub_root / "inventory.yml")
    assert "win-01" in enrolled
    groups = load_inventory_groups(hub_root / "inventory.yml")
    assert "targets" in groups
    assert (
        assert_hosts_allowed(
            "win-01",
            enrolled=enrolled,
            role=Role.HUB,
            groups=groups,
        )
        == "win-01"
    )
    assert (
        assert_hosts_allowed(
            "targets",
            enrolled=enrolled,
            role=Role.HUB,
            groups=groups,
        )
        == "targets"
    )


def test_spoke_call_rejects_target(hub_root: Path):
    from ansible_flow_mcp.hub.state import load_hub_state

    register_target("win-01", ansible_host="10.0.4.1", ansible_connection="winrm", root=hub_root)
    st = load_hub_state(hub_root)
    with pytest.raises(ValueError, match="Ansible target"):
        _spoke_target(st, "win-01")


def test_migration_old_inventory_without_targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "hub"
    monkeypatch.setenv("ANSIBLE_FLOW_HUB_DIR", str(root))
    hub_init(name="hub-01", root=root)
    # Simulate pre-target inventory
    inv = load_inventory(root / "inventory.yml")
    del inv["all"]["children"]["targets"]
    write_inventory(root / "inventory.yml", inv)
    loaded = load_inventory(root / "inventory.yml")
    assert "targets" in loaded["all"]["children"]
    add_target(loaded, name="api-01", ansible_host="10.1.1.1", ansible_connection="ssh")
    assert get_target(loaded, "api-01")["kind"] == "target"
    assert "api-01" in targetable_host_names(loaded)


def test_reserved_group_targets(hub_root: Path):
    inv = load_inventory(hub_root / "inventory.yml")
    with pytest.raises(ValueError, match="reserved"):
        create_group(inv, "targets")


def test_duplicate_register_fails(hub_root: Path):
    register_target("win-01", ansible_host="10.0.4.1", ansible_connection="winrm", root=hub_root)
    with pytest.raises(ValueError, match="already registered"):
        register_target("win-01", ansible_host="10.0.4.2", ansible_connection="winrm", root=hub_root)
