from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

import yaml

from ansible_flow_mcp.paths import hub_dir, spoke_dir


class Role(str, Enum):
    LEGACY = "legacy"
    HUB = "hub"
    SPOKE = "spoke"


@dataclass(frozen=True)
class Mode:
    role: Role
    hub_path: Path | None = None
    spoke_path: Path | None = None


def detect_mode(
    *,
    hub_path: Path | None = None,
    spoke_path: Path | None = None,
    env_role: str | None = None,
) -> Mode:
    role_raw = (env_role or os.environ.get("ANSIBLE_FLOW_ROLE") or "").strip().lower()
    hp = hub_path or (hub_dir() if Path(hub_dir()).is_dir() and (hub_dir() / "hub_id").is_file() else None)
    sp = spoke_path or (
        spoke_dir() if Path(spoke_dir()).is_dir() and (spoke_dir() / "node.yml").is_file() else None
    )

    if role_raw == "hub" or (hp is not None and (hp / "hub_id").is_file() and role_raw != "spoke"):
        if hp is None:
            hp = hub_dir()
        return Mode(role=Role.HUB, hub_path=hp)
    if role_raw == "spoke" or (sp is not None and (sp / "node.yml").is_file()):
        if sp is None:
            sp = spoke_dir()
        return Mode(role=Role.SPOKE, spoke_path=sp)
    return Mode(role=Role.LEGACY)


def load_enrolled_hosts(inventory_path: Path) -> set[str]:
    if not inventory_path.is_file():
        return set()
    data = yaml.safe_load(inventory_path.read_text(encoding="utf-8")) or {}
    names: set[str] = set()
    _walk_hosts(data, names)
    return names


def load_inventory_groups(inventory_path: Path) -> set[str]:
    """Targetable Ansible group names from hub inventory (system + custom)."""
    if not inventory_path.is_file():
        return {"all", "hub", "spokes", "targets", "ungrouped"}
    try:
        from ansible_flow_mcp.hub.inventory import inventory_group_names, load_inventory

        return inventory_group_names(load_inventory(inventory_path))
    except Exception:  # noqa: BLE001
        data = yaml.safe_load(inventory_path.read_text(encoding="utf-8")) or {}
        names = {"all", "hub", "spokes", "targets", "ungrouped"}
        children = ((data.get("all") or {}).get("children") or {}) if isinstance(data, dict) else {}
        if isinstance(children, dict):
            names.update(str(k) for k in children.keys())
        return names


def _walk_hosts(node: object, out: set[str]) -> None:
    if not isinstance(node, dict):
        return
    hosts = node.get("hosts")
    if isinstance(hosts, dict):
        out.update(str(k) for k in hosts)
    elif isinstance(hosts, list):
        out.update(str(h) for h in hosts)
    children = node.get("children")
    if isinstance(children, dict):
        for child in children.values():
            _walk_hosts(child, out)
    # top-level all/children style already covered; also plain group maps
    for key, val in node.items():
        if key in {"hosts", "vars", "children"}:
            continue
        if isinstance(val, dict):
            _walk_hosts(val, out)


def parse_host_pattern(pattern: str) -> list[str]:
    text = (pattern or "").strip()
    if not text:
        return []
    # Simple patterns: comma-separated names, optional trailing comma
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts


def assert_hosts_allowed(
    pattern: str,
    *,
    enrolled: Iterable[str],
    role: Role,
    allow_localhost: bool = True,
    groups: Iterable[str] | None = None,
) -> str:
    """Validate host pattern against role + enrollment. Returns normalized pattern."""
    enrolled_set = {str(h) for h in enrolled}
    parts = parse_host_pattern(pattern)
    if not parts:
        raise ValueError("hosts pattern is empty")

    if role == Role.SPOKE:
        for p in parts:
            if p not in {"localhost", "127.0.0.1"}:
                raise ValueError("spoke mode allows hosts=localhost only")
        return "localhost"

    if role == Role.HUB:
        allowed = set(enrolled_set)
        if allow_localhost:
            allowed.update({"localhost", "127.0.0.1"})
        group_set = {str(g) for g in (groups or ())}
        if not group_set:
            group_set = {"all", "hub", "spokes", "targets", "ungrouped"}
        allowed.update(group_set)
        for p in parts:
            if p in allowed:
                continue
            raise ValueError(
                f"host {p!r} is not an enrolled spoke or registered target on this hub "
                f"(hosts: {', '.join(sorted(enrolled_set)) or 'none'}; "
                f"groups: {', '.join(sorted(group_set))})"
            )
        return ",".join(parts)

    # legacy: no enrollment gate
    return ",".join(parts) if parts else "localhost"


def hub_inventory_path(mode: Mode | None = None) -> Path | None:
    m = mode or detect_mode()
    if m.role != Role.HUB or m.hub_path is None:
        return None
    return m.hub_path / "inventory.yml"
