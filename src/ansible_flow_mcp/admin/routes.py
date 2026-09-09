"""JSON handlers for the hub admin HTTP API (inventory ops only)."""
from __future__ import annotations

from typing import Any
from pathlib import Path

from ansible_flow_mcp.hub.enroll import (
    create_group_op,
    delete_group_op,
    hub_status,
    list_groups_op,
    register_target,
    remove_target_node,
    revoke_node,
    set_group_members_op,
    update_node,
    update_target_node,
)
from ansible_flow_mcp.hub.state import load_hub_state, read_audit
from ansible_flow_mcp.hub.tokens import issue_token
from ansible_flow_mcp.tui import build_spoke_join_command, default_join_hub
from ansible_flow_mcp import __version__


class AdminError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def status(root: Path) -> dict[str, Any]:
    payload = hub_status(root=root)
    payload["ok"] = True
    payload["version"] = __version__
    return payload


def issue_join_token(root: Path, body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("name") or "").strip()
    if not name:
        raise AdminError("name is required")
    ttl = body.get("ttl_seconds", 900)
    try:
        ttl_seconds = int(ttl)
    except (TypeError, ValueError) as exc:
        raise AdminError("ttl_seconds must be an integer") from exc
    st = load_hub_state(root)
    issued = issue_token(name, ttl_seconds=ttl_seconds, state=st)
    join_hub = str(body.get("hub") or "").strip() or default_join_hub()
    public_addr = str(body.get("public_addr") or "").strip() or name
    payload = issued.to_dict()
    payload["ok"] = True
    payload["join_hub"] = join_hub
    payload["public_addr"] = public_addr
    payload["join_command"] = build_spoke_join_command(
        token=issued.token,
        hub=join_hub,
        name=name,
        public_addr=public_addr,
    )
    return payload


def patch_node(root: Path, name: str, body: dict[str, Any]) -> dict[str, Any]:
    port = body.get("ansible_port")
    ansible_port = int(port) if port not in (None, "") else None
    return update_node(
        name,
        ansible_host=body.get("ansible_host"),
        ansible_port=ansible_port,
        ansible_user=body.get("ansible_user"),
        root=root,
    )


def ping_spoke(root: Path, name: str) -> dict[str, Any]:
    from ansible_flow_mcp.ssh import spoke_call

    result = spoke_call(name, tool="list_collections", arguments={}, root=root, timeout=30)
    return result.to_dict()


def create_target(root: Path, body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("name") or "").strip()
    host = str(body.get("ansible_host") or "").strip()
    if not name or not host:
        raise AdminError("name and ansible_host are required")
    extra = body.get("extra")
    if extra is not None and not isinstance(extra, dict):
        raise AdminError("extra must be an object")
    port = body.get("ansible_port")
    ansible_port = int(port) if port not in (None, "") else None
    return register_target(
        name,
        ansible_host=host,
        ansible_connection=str(body.get("ansible_connection") or "ssh"),
        ansible_port=ansible_port,
        ansible_user=body.get("ansible_user"),
        extra=extra,
        root=root,
    )


def patch_target(root: Path, name: str, body: dict[str, Any]) -> dict[str, Any]:
    extra = body.get("extra")
    if extra is not None and not isinstance(extra, dict):
        raise AdminError("extra must be an object")
    port = body.get("ansible_port")
    ansible_port = int(port) if port not in (None, "") else None
    return update_target_node(
        name,
        ansible_host=body.get("ansible_host"),
        ansible_port=ansible_port,
        ansible_user=body.get("ansible_user"),
        ansible_connection=body.get("ansible_connection"),
        extra=extra,
        root=root,
    )


def create_group(root: Path, body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("name") or "").strip()
    if not name:
        raise AdminError("name is required")
    return create_group_op(name, root=root)


def set_members(root: Path, name: str, body: dict[str, Any]) -> dict[str, Any]:
    hosts = body.get("hosts")
    if not isinstance(hosts, list):
        raise AdminError("hosts must be an array of names")
    return set_group_members_op(name, [str(h) for h in hosts], root=root)


def groups(root: Path) -> dict[str, Any]:
    return list_groups_op(root=root)


def audit(root: Path, limit: int = 100) -> dict[str, Any]:
    return {"ok": True, "events": read_audit(root=root, limit=limit)}


def revoke(root: Path, name: str) -> dict[str, Any]:
    return revoke_node(name, root=root)


def remove_target(root: Path, name: str) -> dict[str, Any]:
    return remove_target_node(name, root=root)


def delete_group(root: Path, name: str) -> dict[str, Any]:
    return delete_group_op(name, root=root)
