from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from ansible_flow_mcp.paths import ensure_dir


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
                        }
                    }
                },
                "spokes": {"hosts": {}},
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
    return data


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


def list_spoke_names(inv: dict[str, Any]) -> list[str]:
    hosts = _spokes_hosts(inv)
    return sorted(str(k) for k in hosts.keys())


def add_spoke(
    inv: dict[str, Any],
    *,
    name: str,
    ansible_host: str,
    ansible_port: int = 22,
    ansible_user: str = "mcp-ansible",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hosts = _spokes_hosts(inv)
    entry: dict[str, Any] = {
        "ansible_host": ansible_host,
        "ansible_port": int(ansible_port),
        "ansible_user": ansible_user,
        "mesh_user": "mcp-spoke",
        "mesh_role": "spoke",
    }
    if extra:
        entry.update(extra)
    hosts[name] = entry
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
        return {"name": name}
    out = dict(meta)
    out["name"] = name
    out["groups"] = groups_for_host(inv, name)
    return out


def list_spokes_detail(inv: dict[str, Any]) -> list[dict[str, Any]]:
    return [get_spoke(inv, n) or {"name": n} for n in list_spoke_names(inv)]


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
            if k in {"name", "mesh_role"}:
                continue
            entry[k] = v
    entry.setdefault("mesh_role", "spoke")
    return get_spoke(inv, name) or {"name": name}


def rename_spoke(inv: dict[str, Any], old: str, new: str) -> dict[str, Any]:
    old_n = (old or "").strip()
    new_n = (new or "").strip()
    if not old_n or not new_n:
        raise ValueError("old and new names required")
    if old_n == new_n:
        return get_spoke(inv, old_n) or {"name": old_n}
    hosts = _spokes_hosts(inv)
    if old_n not in hosts:
        raise KeyError(f"spoke not enrolled: {old_n}")
    if new_n in hosts:
        raise ValueError(f"spoke already exists: {new_n}")
    hosts[new_n] = hosts.pop(old_n)
    for gname in list_custom_group_names(inv):
        ghosts = _group_hosts_dict(inv, gname)
        if old_n in ghosts:
            ghosts[new_n] = ghosts.pop(old_n)
    return get_spoke(inv, new_n) or {"name": new_n}


RESERVED_GROUPS = frozenset({"all", "hub", "spokes", "ungrouped"})


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
    enrolled = set(list_spoke_names(inv))
    cleaned: list[str] = []
    for h in hosts:
        hn = str(h).strip()
        if not hn:
            continue
        if hn not in enrolled:
            raise ValueError(f"host {hn!r} is not an enrolled spoke")
        cleaned.append(hn)
    ghosts = _group_hosts_dict(inv, gname)
    ghosts.clear()
    for hn in cleaned:
        ghosts[hn] = {}
    return {"name": gname, "hosts": sorted(cleaned)}


def add_to_group(inv: dict[str, Any], name: str, host: str) -> dict[str, Any]:
    gname = _validate_group_name(name)
    hn = (host or "").strip()
    if hn not in list_spoke_names(inv):
        raise ValueError(f"host {hn!r} is not an enrolled spoke")
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
