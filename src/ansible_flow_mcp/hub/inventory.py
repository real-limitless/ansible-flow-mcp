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
                "ansible_user": "mcp-spoke",
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
    ansible_user: str = "mcp-spoke",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hosts = _spokes_hosts(inv)
    entry: dict[str, Any] = {
        "ansible_host": ansible_host,
        "ansible_port": int(ansible_port),
        "ansible_user": ansible_user,
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
        return True
    return False


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
