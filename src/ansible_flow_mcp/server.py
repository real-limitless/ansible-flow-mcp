from __future__ import annotations

import json
import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from ansible_flow_mcp import __version__
from ansible_flow_mcp.catalog import get_module_schema, list_collections, search_modules
from ansible_flow_mcp.policy import Role, detect_mode
from ansible_flow_mcp.runner import run_module, run_playbook
from ansible_flow_mcp.security import load_policy

_ROLE: str | None = None


def _role() -> Role:
    if _ROLE == "hub":
        return Role.HUB
    if _ROLE == "spoke":
        return Role.SPOKE
    return detect_mode().role


def _instructions() -> str:
    role = _role()
    base = (
        "Ansible module/playbook runner for agents. Ritual: search_modules → "
        "get_module_schema → run_module(check_mode=true) → run_module(check_mode=false). "
        "For playbooks: run_playbook(check_mode=true) first. "
        "Never request denied free-form modules (command/shell/raw/script). "
        "Playbooks must be .yml under allowlisted roots. Prefer check mode before applying."
    )
    if role == Role.HUB:
        return (
            base
            + " HUB mode: inventory is fixed (enrolled spokes + registered Ansible targets); "
            "do not pass custom inventory. "
            "Spokes: issue_token → spoke join (mesh + SSH). "
            "Targets (Windows/WinRM, network, etc. — no agent): register_target / update_target / "
            "remove_target. "
            "Use list_nodes / hub_status / update_node / revoke_node / list_groups / "
            "create_group / set_group_members. spoke_call is mesh spokes only (not targets). "
            "hosts must be spoke or target names, inventory groups, or localhost."
        )
    if role == Role.SPOKE:
        return base + " SPOKE mode: localhost execution only. No issue_token or foreign hosts."
    return base


mcp = FastMCP("ansible-flow-mcp", instructions=_instructions())


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


@mcp.tool(name="search_modules")
def search_modules_tool(query: str = "", limit: int = 25) -> str:
    """Search allowlisted Ansible modules (gallery) by name, FQCN, collection, or description."""
    hits = search_modules(query, limit=limit)
    return _json({"count": len(hits), "items": hits})


@mcp.tool(name="get_module_schema")
def get_module_schema_tool(module: str) -> str:
    """Return slim arg schema for a module FQCN (when catalog has it)."""
    policy = load_policy()
    fqcn = policy.assert_module_allowed(module)
    schema = get_module_schema(fqcn)
    if schema is None:
        from ansible_flow_mcp.catalog import catalog_dir

        return _json(
            {
                "fqcn": fqcn,
                "schema": None,
                "catalogDir": str(catalog_dir()),
                "message": (
                    "No committed schema JSON for this FQCN under catalog/schemas/. "
                    "Pass args as a free-form object to run_module, or rebuild the "
                    "install/image so catalog/schemas is included."
                ),
            }
        )
    return _json(schema)


@mcp.tool(name="run_module")
def run_module_tool(
    module: str,
    args: dict[str, Any] | None = None,
    hosts: str = "localhost",
    inventory: str | None = None,
    check_mode: bool = True,
    become: bool = False,
    become_user: str | None = None,
    connection: str | None = None,
    timeout: float = 120,
) -> str:
    """Run an Ansible module via local ansible CLI. Prefer check_mode=true first."""
    result = run_module(
        module,
        args=args,
        hosts=hosts,
        inventory=inventory,
        check_mode=check_mode,
        become=become,
        become_user=become_user,
        connection=connection,
        timeout=timeout,
    )
    payload = result.to_dict()
    payload["stdout"] = (payload.get("stdout") or "")[:8000]
    payload["stderr"] = (payload.get("stderr") or "")[:4000]
    return _json(payload)


@mcp.tool(name="run_playbook")
def run_playbook_tool(
    playbook: str,
    inventory: str | None = None,
    check_mode: bool = True,
    become: bool = False,
    become_user: str | None = None,
    connection: str | None = None,
    extra_vars: dict[str, Any] | None = None,
    limit: str | None = None,
    tags: str | None = None,
    skip_tags: str | None = None,
    timeout: float = 300,
) -> str:
    """Run ansible-playbook on a path under allowlisted roots. Prefer check_mode=true first."""
    result = run_playbook(
        playbook,
        inventory=inventory,
        check_mode=check_mode,
        become=become,
        become_user=become_user,
        connection=connection,
        extra_vars=extra_vars,
        limit=limit,
        tags=tags,
        skip_tags=skip_tags,
        timeout=timeout,
    )
    payload = result.to_dict()
    payload["stdout"] = (payload.get("stdout") or "")[:8000]
    payload["stderr"] = (payload.get("stderr") or "")[:4000]
    return _json(payload)


@mcp.tool(name="list_collections")
def list_collections_tool() -> str:
    """List collections present in the committed gallery."""
    return _json({"collections": list_collections(), "version": __version__, "role": _role().value})


def _register_hub_tools() -> None:
    @mcp.tool(name="list_nodes")
    def list_nodes_tool() -> str:
        """List enrolled spokes and registered Ansible targets (kind, connection, groups)."""
        from ansible_flow_mcp.hub.enroll import hub_status

        return _json(hub_status())

    @mcp.tool(name="hub_status")
    def hub_status_tool() -> str:
        """Hub controller status (inventory path, spokes, targets, groups)."""
        from ansible_flow_mcp.hub.enroll import hub_status

        return _json(hub_status())

    @mcp.tool(name="issue_token")
    def issue_token_tool(name: str, ttl_seconds: int = 900) -> str:
        """Issue a one-time spoke join token (hub only). Not used for Ansible targets."""
        from ansible_flow_mcp.hub.tokens import issue_token

        issued = issue_token(name, ttl_seconds=ttl_seconds)
        return _json(issued.to_dict())

    @mcp.tool(name="revoke_node")
    def revoke_node_tool(name: str) -> str:
        """Remove spoke from hub inventory and mark revoked."""
        from ansible_flow_mcp.hub.enroll import revoke_node

        return _json(revoke_node(name))

    @mcp.tool(name="update_node")
    def update_node_tool(
        name: str,
        ansible_host: str | None = None,
        ansible_port: int | None = None,
        ansible_user: str | None = None,
    ) -> str:
        """Update enrolled spoke connection fields (host/port/user). For targets use update_target."""
        from ansible_flow_mcp.hub.enroll import update_node

        return _json(
            update_node(
                name,
                ansible_host=ansible_host,
                ansible_port=ansible_port,
                ansible_user=ansible_user,
            )
        )

    @mcp.tool(name="register_target")
    def register_target_tool(
        name: str,
        ansible_host: str,
        ansible_connection: str = "ssh",
        ansible_port: int | None = None,
        ansible_user: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Register an Ansible-only target (WinRM/SSH/network) — no spoke agent or join token.

        Do not pass passwords in extra; use hub-side Ansible config or path refs under hub dir.
        """
        from ansible_flow_mcp.hub.enroll import register_target

        return _json(
            register_target(
                name,
                ansible_host=ansible_host,
                ansible_connection=ansible_connection,
                ansible_port=ansible_port,
                ansible_user=ansible_user,
                extra=extra,
            )
        )

    @mcp.tool(name="update_target")
    def update_target_tool(
        name: str,
        ansible_host: str | None = None,
        ansible_port: int | None = None,
        ansible_user: str | None = None,
        ansible_connection: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Update a registered Ansible target connection fields."""
        from ansible_flow_mcp.hub.enroll import update_target_node

        return _json(
            update_target_node(
                name,
                ansible_host=ansible_host,
                ansible_port=ansible_port,
                ansible_user=ansible_user,
                ansible_connection=ansible_connection,
                extra=extra,
            )
        )

    @mcp.tool(name="remove_target")
    def remove_target_tool(name: str) -> str:
        """Remove a registered Ansible target from hub inventory and groups."""
        from ansible_flow_mcp.hub.enroll import remove_target_node

        return _json(remove_target_node(name))

    @mcp.tool(name="list_groups")
    def list_groups_tool() -> str:
        """List custom targeting groups and their members (spokes and/or targets)."""
        from ansible_flow_mcp.hub.enroll import list_groups_op

        return _json(list_groups_op())

    @mcp.tool(name="create_group")
    def create_group_tool(name: str) -> str:
        """Create an empty targeting group (members must be spokes or targets)."""
        from ansible_flow_mcp.hub.enroll import create_group_op

        return _json(create_group_op(name))

    @mcp.tool(name="delete_group")
    def delete_group_tool(name: str) -> str:
        """Delete a custom targeting group (not hub/spokes/targets)."""
        from ansible_flow_mcp.hub.enroll import delete_group_op

        return _json(delete_group_op(name))

    @mcp.tool(name="set_group_members")
    def set_group_members_tool(name: str, hosts: list[str]) -> str:
        """Replace group membership with enrolled spoke and/or registered target names."""
        from ansible_flow_mcp.hub.enroll import set_group_members_op

        return _json(set_group_members_op(name, hosts))

    @mcp.tool(name="spoke_call")
    def spoke_call_tool(
        node: str,
        tool: str = "list_collections",
        arguments: dict[str, Any] | None = None,
        timeout: float = 60,
    ) -> str:
        """SSH to an enrolled mesh spoke ForceCommand MCP and call one tool (not for targets)."""
        from ansible_flow_mcp.ssh import spoke_call

        result = spoke_call(node, tool=tool, arguments=arguments or {}, timeout=timeout)
        return _json(result.to_dict())


def run_server(*, role: str | None = None) -> None:
    global _ROLE
    _ROLE = role
    if role == "hub" or (role is None and detect_mode().role == Role.HUB):
        if os.environ.get("ANSIBLE_FLOW_ROLE", "").lower() != "spoke":
            os.environ.setdefault("ANSIBLE_FLOW_ROLE", "hub")
            _register_hub_tools()
    elif role == "spoke":
        os.environ["ANSIBLE_FLOW_ROLE"] = "spoke"
    mcp.run(transport="stdio")


def main() -> None:
    # Prefer CLI dispatcher when invoked as console script with args
    if len(sys.argv) > 1:
        from ansible_flow_mcp.cli import main as cli_main

        cli_main()
        return
    run_server(role=None)


if __name__ == "__main__":
    main()
    sys.exit(0)
