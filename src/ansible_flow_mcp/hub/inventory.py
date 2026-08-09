from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from ansible_flow_mcp.paths import ensure_dir


KIND_SPOKE = "spoke"
KIND_TARGET = "target"
KIND_HUB = "hub"

# Connection plugins allowed on register_target (MVP).
ALLOWED_TARGET_CONNECTIONS = frozenset(
    {
        "ssh",
        "smart",
        "paramiko",
        "local",
        "winrm",
        "psrp",
        "network_cli",
        "httpapi",
        "netconf",
    }
)

# Extra host vars allowed on targets (no secrets inline — path refs only).
ALLOWED_TARGET_EXTRA_KEYS = frozenset(
    {
        "ansible_host",
        "ansible_port",
        "ansible_user",
        "ansible_connection",
        "ansible_ssh_private_key_file",
        "ansible_winrm_transport",
        "ansible_winrm_server_cert_validation",
        "ansible_winrm_scheme",
        "ansible_winrm_path",
        "ansible_winrm_connection_timeout",
        "ansible_psrp_protocol",
        "ansible_network_os",
        "ansible_become",
        "ansible_become_method",
        "ansible_become_user",
        "ansible_python_interpreter",
        "ansible_shell_type",
        "ansible_flow_labels",
    }
)

# Never persist or echo these on target entries.
SECRET_TARGET_KEYS = frozenset(
    {
        "ansible_password",
        "ansible_ssh_pass",
        "ansible_become_password",
        "ansible_winrm_password",
        "ansible_winrm_cert_pem",
        "ansible_winrm_cert_key_pem",
        "ansible_psrp_password",
        "password",
        "secret",
        "token",
    }
)


def default_inventory(*, hub_name: str = "hub-01") -> dict[str, Any]:
    return {
        "all": {
            "children": {
                "hub": {
                    "hosts": {
                        hub_name: {
                            "ansible_host": "127.0.0.1",
                            "ansible_connection": "local",
                            "mesh_role": "hub",
                            "ansible_flow_kind": KIND_HUB,
                        }
                    }
                },
                "spokes": {"hosts": {}},
                "targets": {"hosts": {}},
            },
            "vars": {
                # Shell user for ansible CLI (NOT mcp-spoke — that is ForceCommand MCP only)
                "ansible_user": "mcp-ansible",
                "ansible_ssh_common_args": (
                    "-o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
                    "-o BatchMode=yes -o PasswordAuthentication=no"
                ),
            },
        }
    }


def load_inventory(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return default_inventory()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return default_inventory()
    ensure_targets_group(data)
    return data


def ensure_targets_group(inv: dict[str, Any]) -> dict[str, Any]:
    """Ensure system group targets exists (migration for pre-target inventories)."""
    _targets_hosts(inv)
    return inv


def write_inventory(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _spokes_hosts(inv: dict[str, Any]) -> dict[str, Any]:
    all_n = inv.setdefault("all", {})
    children = all_n.setdefault("children", {})
    spokes = children.setdefault("spokes", {})
    hosts = spokes.setdefault("hosts", {})
    if not isinstance(hosts, dict):
        hosts = {}
        spokes["hosts"] = hosts
    return hosts


def _targets_hosts(inv: dict[str, Any]) -> dict[str, Any]:
    all_n = inv.setdefault("all", {})
    children = all_n.setdefault("children", {})
    targets = children.setdefault("targets", {})
    if not isinstance(targets, dict):
        targets = {}
        children["targets"] = targets
    hosts = targets.setdefault("hosts", {})
    if not isinstance(hosts, dict):
        hosts = {}
        targets["hosts"] = hosts
    return hosts


def _hub_host_names(inv: dict[str, Any]) -> set[str]:
    children = (inv.get("all") or {}).get("children") or {}
    hub = children.get("hub") if isinstance(children, dict) else None
    hosts = (hub or {}).get("hosts") if isinstance(hub, dict) else None
    if not isinstance(hosts, dict):
        return set()
    return {str(k) for k in hosts.keys()}


def _validate_node_name(name: str) -> str:
    n = (name or "").strip()
    if not n or "/" in n or " " in n:
        raise ValueError("name must be a non-empty token without spaces")
    if not n.replace("_", "").replace("-", "").replace(".", "").isalnum():
        raise ValueError(f"invalid node name: {n}")
    return n


def assert_name_available(
    inv: dict[str, Any],
    name: str,
    *,
    for_kind: str,
    allow_replace_same_kind: bool = False,
) -> str:
    n = _validate_node_name(name)
    if n in RESERVED_GROUPS or n in {"localhost", "127.0.0.1"}:
        raise ValueError(f"reserved name: {n}")
    if n in _hub_host_names(inv):
        raise ValueError(f"name conflicts with hub host: {n}")
    spokes = set(list_spoke_names(inv))
    targets = set(list_target_names(inv))
    if for_kind == KIND_SPOKE and n in targets:
        raise ValueError(f"name {n!r} is already an Ansible target")
    if for_kind == KIND_TARGET and n in spokes:
        raise ValueError(f"name {n!r} is already an enrolled spoke")
    if for_kind == KIND_SPOKE and n in spokes and not allow_replace_same_kind:
        raise ValueError(f"spoke already enrolled: {n}")
    if for_kind == KIND_TARGET and n in targets and not allow_replace_same_kind:
        raise ValueError(f"target already registered: {n}")
    return n


def list_spoke_names(inv: dict[str, Any]) -> list[str]:
    hosts = _spokes_hosts(inv)
    return sorted(str(k) for k in hosts.keys())


def list_target_names(inv: dict[str, Any]) -> list[str]:
    hosts = _targets_hosts(inv)
    return sorted(str(k) for k in hosts.keys())


def targetable_host_names(inv: dict[str, Any]) -> set[str]:
    """Spokes + targets (membership for groups and run_module hosts)."""
    return set(list_spoke_names(inv)) | set(list_target_names(inv))


def public_host_view(meta: dict[str, Any], *, name: str, kind: str) -> dict[str, Any]:
    """Safe projection for status/MCP (strip secret-shaped keys)."""
    out: dict[str, Any] = {"name": name, "kind": kind, "ansible_flow_kind": kind}
    for k, v in meta.items():
        lk = str(k).lower()
        if k in SECRET_TARGET_KEYS or lk in SECRET_TARGET_KEYS:
            continue
        if any(s in lk for s in ("password", "secret", "token", "private_key_data")):
            continue
        if k in {"name"}:
            continue
        out[k] = v
    return out


def add_spoke(
    inv: dict[str, Any],
    *,
    name: str,
    ansible_host: str,
    ansible_port: int = 22,
    ansible_user: str = "mcp-ansible",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_targets_group(inv)
    # Join may re-enroll the same spoke name (overwrite inventory row).
    n = assert_name_available(inv, name, for_kind=KIND_SPOKE, allow_replace_same_kind=True)
    hosts = _spokes_hosts(inv)
    entry: dict[str, Any] = {
        "ansible_host": ansible_host,
        "ansible_port": int(ansible_port),
        "ansible_user": ansible_user,
        "mesh_user": "mcp-spoke",
        "mesh_role": "spoke",
        "ansible_flow_kind": KIND_SPOKE,
    }
    if extra:
        for k, v in extra.items():
            if k in SECRET_TARGET_KEYS or k in {"name", "ansible_flow_kind"}:
                continue
            entry[k] = v
    hosts[n] = entry
    # pin key path if present under vars
    vars_n = inv.setdefault("all", {}).setdefault("vars", {})
    vars_n.setdefault("ansible_user", ansible_user)
    return inv


def remove_spoke(inv: dict[str, Any], name: str) -> bool:
    hosts = _spokes_hosts(inv)
    if name in hosts:
        del hosts[name]
        # drop from custom groups
        for gname in list_custom_group_names(inv):
            remove_from_group(inv, gname, name)
        return True
    return False


def get_spoke(inv: dict[str, Any], name: str) -> dict[str, Any] | None:
    hosts = _spokes_hosts(inv)
    meta = hosts.get(name)
    if meta is None:
        return None
    if not isinstance(meta, dict):
        meta = {}
    out = public_host_view(meta, name=name, kind=KIND_SPOKE)
    out["groups"] = groups_for_host(inv, name)
    return out


def list_spokes_detail(inv: dict[str, Any]) -> list[dict[str, Any]]:
    return [get_spoke(inv, n) or {"name": n, "kind": KIND_SPOKE} for n in list_spoke_names(inv)]


def add_target(
    inv: dict[str, Any],
    *,
    name: str,
    ansible_host: str,
    ansible_connection: str = "ssh",
    ansible_port: int | None = None,
    ansible_user: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_targets_group(inv)
    n = assert_name_available(inv, name, for_kind=KIND_TARGET)
    conn = (ansible_connection or "ssh").strip().lower()
    if conn not in ALLOWED_TARGET_CONNECTIONS:
        raise ValueError(
            f"unsupported connection {conn!r}; allowed: {', '.join(sorted(ALLOWED_TARGET_CONNECTIONS))}"
        )
    host = (ansible_host or "").strip()
    if not host:
        raise ValueError("ansible_host is required")
    entry: dict[str, Any] = {
        "ansible_host": host,
        "ansible_connection": conn,
        "ansible_flow_kind": KIND_TARGET,
    }
    if ansible_port is not None:
        entry["ansible_port"] = int(ansible_port)
    elif conn == "winrm":
        entry["ansible_port"] = 5986
    elif conn in {"ssh", "smart", "paramiko", "network_cli", "netconf"}:
        entry["ansible_port"] = 22
    if ansible_user is not None and str(ansible_user).strip():
        entry["ansible_user"] = str(ansible_user).strip()
    if extra:
        for k, v in extra.items():
            key = str(k)
            if key in SECRET_TARGET_KEYS or key in {"name", "mesh_role", "mesh_user", "ansible_flow_kind"}:
                raise ValueError(f"refusing secret or reserved key on target: {key}")
            if key not in ALLOWED_TARGET_EXTRA_KEYS:
                raise ValueError(f"unsupported target var: {key}")
            entry[key] = v
    _targets_hosts(inv)[n] = entry
    return inv


def remove_target(inv: dict[str, Any], name: str) -> bool:
    hosts = _targets_hosts(inv)
    if name in hosts:
        del hosts[name]
        for gname in list_custom_group_names(inv):
            remove_from_group(inv, gname, name)
        return True
    return False


def get_target(inv: dict[str, Any], name: str) -> dict[str, Any] | None:
    hosts = _targets_hosts(inv)
    meta = hosts.get(name)
    if meta is None:
        return None
    if not isinstance(meta, dict):
        meta = {}
    out = public_host_view(meta, name=name, kind=KIND_TARGET)
    out["groups"] = groups_for_host(inv, name)
    return out


def list_targets_detail(inv: dict[str, Any]) -> list[dict[str, Any]]:
    return [get_target(inv, n) or {"name": n, "kind": KIND_TARGET} for n in list_target_names(inv)]


def update_target(
    inv: dict[str, Any],
    name: str,
    *,
    ansible_host: str | None = None,
    ansible_port: int | None = None,
    ansible_user: str | None = None,
    ansible_connection: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hosts = _targets_hosts(inv)
    if name not in hosts:
        raise KeyError(f"target not registered: {name}")
    entry = hosts[name]
    if not isinstance(entry, dict):
        entry = {}
        hosts[name] = entry
    if ansible_host is not None:
        h = str(ansible_host).strip()
        if not h:
            raise ValueError("ansible_host cannot be empty")
        entry["ansible_host"] = h
    if ansible_port is not None:
        entry["ansible_port"] = int(ansible_port)
    if ansible_user is not None:
        entry["ansible_user"] = str(ansible_user).strip()
    if ansible_connection is not None:
        conn = str(ansible_connection).strip().lower()
        if conn not in ALLOWED_TARGET_CONNECTIONS:
            raise ValueError(f"unsupported connection {conn!r}")
        entry["ansible_connection"] = conn
    if extra:
        for k, v in extra.items():
            key = str(k)
            if key in SECRET_TARGET_KEYS or key in {"name", "mesh_role", "mesh_user", "ansible_flow_kind"}:
                raise ValueError(f"refusing secret or reserved key on target: {key}")
            if key not in ALLOWED_TARGET_EXTRA_KEYS:
                raise ValueError(f"unsupported target var: {key}")
            entry[key] = v
    entry["ansible_flow_kind"] = KIND_TARGET
    entry.pop("mesh_role", None)
    entry.pop("mesh_user", None)
    return get_target(inv, name) or {"name": name, "kind": KIND_TARGET}


def update_spoke(
    inv: dict[str, Any],
    name: str,
    *,
    ansible_host: str | None = None,
    ansible_port: int | None = None,
    ansible_user: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hosts = _spokes_hosts(inv)
    if name not in hosts:
        raise KeyError(f"spoke not enrolled: {name}")
    entry = hosts[name]
    if not isinstance(entry, dict):
        entry = {}
        hosts[name] = entry
    if ansible_host is not None:
        entry["ansible_host"] = str(ansible_host).strip()
    if ansible_port is not None:
        entry["ansible_port"] = int(ansible_port)
    if ansible_user is not None:
        entry["ansible_user"] = str(ansible_user).strip()
    if extra:
        for k, v in extra.items():
            if k in {"name", "mesh_role", "ansible_flow_kind"} or k in SECRET_TARGET_KEYS:
                continue
            entry[k] = v
    entry.setdefault("mesh_role", "spoke")
    entry["ansible_flow_kind"] = KIND_SPOKE
    return get_spoke(inv, name) or {"name": name, "kind": KIND_SPOKE}


def list_nodes_detail(inv: dict[str, Any]) -> list[dict[str, Any]]:
    """Spokes + targets for hub_status / list_nodes."""
    return list_spokes_detail(inv) + list_targets_detail(inv)


def rename_spoke(inv: dict[str, Any], old: str, new: str) -> dict[str, Any]:
    old_n = (old or "").strip()
    new_n = (new or "").strip()
    if not old_n or not new_n:
        raise ValueError("old and new names required")
    if old_n == new_n:
        return get_spoke(inv, old_n) or {"name": old_n, "kind": KIND_SPOKE}
    hosts = _spokes_hosts(inv)
    if old_n not in hosts:
        raise KeyError(f"spoke not enrolled: {old_n}")
    assert_name_available(inv, new_n, for_kind=KIND_SPOKE)
    hosts[new_n] = hosts.pop(old_n)
    for gname in list_custom_group_names(inv):
        ghosts = _group_hosts_dict(inv, gname)
        if old_n in ghosts:
            ghosts[new_n] = ghosts.pop(old_n)
    return get_spoke(inv, new_n) or {"name": new_n, "kind": KIND_SPOKE}


RESERVED_GROUPS = frozenset({"all", "hub", "spokes", "targets", "ungrouped"})


def _children(inv: dict[str, Any]) -> dict[str, Any]:
    all_n = inv.setdefault("all", {})
    children = all_n.setdefault("children", {})
    if not isinstance(children, dict):
        children = {}
        all_n["children"] = children
    return children


def _group_hosts_dict(inv: dict[str, Any], name: str) -> dict[str, Any]:
    children = _children(inv)
    grp = children.setdefault(name, {})
    if not isinstance(grp, dict):
        grp = {}
        children[name] = grp
    hosts = grp.setdefault("hosts", {})
    if not isinstance(hosts, dict):
        hosts = {}
        grp["hosts"] = hosts
    return hosts


def list_custom_group_names(inv: dict[str, Any]) -> list[str]:
    children = _children(inv)
    return sorted(str(k) for k in children.keys() if str(k) not in RESERVED_GROUPS)


def list_groups(inv: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in list_custom_group_names(inv):
        hosts = _group_hosts_dict(inv, name)
        out.append({"name": name, "hosts": sorted(str(h) for h in hosts.keys())})
    return out


def groups_for_host(inv: dict[str, Any], host: str) -> list[str]:
    return [g["name"] for g in list_groups(inv) if host in g["hosts"]]


def create_group(inv: dict[str, Any], name: str) -> dict[str, Any]:
    gname = _validate_group_name(name)
    children = _children(inv)
    if gname in children:
        raise ValueError(f"group already exists: {gname}")
    children[gname] = {"hosts": {}}
    return {"name": gname, "hosts": []}


def delete_group(inv: dict[str, Any], name: str) -> bool:
    gname = _validate_group_name(name)
    children = _children(inv)
    if gname not in children:
        return False
    del children[gname]
    return True


def set_group_members(inv: dict[str, Any], name: str, hosts: list[str]) -> dict[str, Any]:
    gname = _validate_group_name(name)
    children = _children(inv)
    if gname not in children and gname not in RESERVED_GROUPS:
        children[gname] = {"hosts": {}}
    elif gname not in children:
        raise ValueError(f"cannot set members on reserved group: {gname}")
    enrolled = targetable_host_names(inv)
    cleaned: list[str] = []
    for h in hosts:
        hn = str(h).strip()
        if not hn:
            continue
        if hn not in enrolled:
            raise ValueError(
                f"host {hn!r} is not an enrolled spoke or registered target"
            )
        cleaned.append(hn)
    ghosts = _group_hosts_dict(inv, gname)
    ghosts.clear()
    for hn in cleaned:
        ghosts[hn] = {}
    return {"name": gname, "hosts": sorted(cleaned)}


def add_to_group(inv: dict[str, Any], name: str, host: str) -> dict[str, Any]:
    gname = _validate_group_name(name)
    hn = (host or "").strip()
    if hn not in targetable_host_names(inv):
        raise ValueError(f"host {hn!r} is not an enrolled spoke or registered target")
    children = _children(inv)
    if gname not in children:
        create_group(inv, gname)
    _group_hosts_dict(inv, gname)[hn] = {}
    return {"name": gname, "hosts": sorted(_group_hosts_dict(inv, gname).keys())}


def remove_from_group(inv: dict[str, Any], name: str, host: str) -> dict[str, Any]:
    gname = (name or "").strip()
    if gname in RESERVED_GROUPS:
        raise ValueError(f"cannot modify reserved group: {gname}")
    hn = (host or "").strip()
    children = _children(inv)
    if gname not in children:
        return {"name": gname, "hosts": []}
    ghosts = _group_hosts_dict(inv, gname)
    ghosts.pop(hn, None)
    return {"name": gname, "hosts": sorted(str(h) for h in ghosts.keys())}


def inventory_group_names(inv: dict[str, Any]) -> set[str]:
    """All targetable group names (system + custom)."""
    names = set(RESERVED_GROUPS) | set(list_custom_group_names(inv))
    names.add("all")
    return names


def _validate_group_name(name: str) -> str:
    gname = (name or "").strip()
    if not gname or "/" in gname or " " in gname:
        raise ValueError("group name must be a non-empty token without spaces")
    if gname in RESERVED_GROUPS:
        raise ValueError(f"reserved group name: {gname}")
    if not gname.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"invalid group name: {gname}")
    return gname


def set_ansible_key_vars(inv: dict[str, Any], private_key_path: Path) -> None:
    vars_n = inv.setdefault("all", {}).setdefault("vars", {})
    vars_n["ansible_ssh_private_key_file"] = str(private_key_path)
    vars_n.setdefault(
        "ansible_ssh_common_args",
        "-o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o BatchMode=yes",
    )


def enrolled_host_names(inv: dict[str, Any]) -> set[str]:
    """All inventory hostnames including hub system hosts (for policy walk)."""
    names: set[str] = set()
    all_n = inv.get("all") or {}
    children = all_n.get("children") or {}
    if not isinstance(children, dict):
        return names
    for group in children.values():
        if not isinstance(group, dict):
            continue
        hosts = group.get("hosts") or {}
        if isinstance(hosts, dict):
            names.update(str(k) for k in hosts)
    return names
