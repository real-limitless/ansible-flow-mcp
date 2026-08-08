from __future__ import annotations

import json
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from ansible_flow_mcp import __version__
from ansible_flow_mcp.catalog import get_module_schema, list_collections, search_modules
from ansible_flow_mcp.runner import run_module
from ansible_flow_mcp.security import load_policy

mcp = FastMCP(
    "ansible-flow-mcp",
    instructions=(
        "Ansible module runner for agents. Ritual: search_modules → "
        "get_module_schema → run_module(check_mode=true) → run_module(check_mode=false). "
        "Never request denied free-form modules (command/shell/raw/script). "
        "Prefer check mode before applying changes."
    ),
)


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
        return _json(
            {
                "fqcn": fqcn,
                "schema": None,
                "message": "No committed schema; pass args as a free-form object to run_module.",
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


@mcp.tool(name="list_collections")
def list_collections_tool() -> str:
    """List collections present in the committed gallery."""
    return _json({"collections": list_collections(), "version": __version__})


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
    sys.exit(0)
