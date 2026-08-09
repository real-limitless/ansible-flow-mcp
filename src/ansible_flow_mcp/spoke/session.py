from __future__ import annotations

import json
import os
import sys
from typing import Any


def _try_simple_exec_line(line: str) -> dict[str, Any] | None:
    """If line is hub simple-exec protocol, run tool and return response dict."""
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, dict) or msg.get("ansible_flow") != 1 or msg.get("op") != "call":
        return None

    tool = str(msg.get("tool") or "")
    arguments = msg.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}

    try:
        result = _dispatch_tool(tool, arguments)
        return {"ok": True, "tool": tool, "result": result}
    except Exception as exc:  # noqa: BLE001 — boundary for ForceCommand
        return {"ok": False, "tool": tool, "error": str(exc)}


def _dispatch_tool(tool: str, arguments: dict[str, Any]) -> Any:
    """Call the same logic as MCP tools without starting the MCP event loop."""
    from ansible_flow_mcp import __version__
    from ansible_flow_mcp.catalog import get_module_schema, list_collections, search_modules
    from ansible_flow_mcp.runner import run_module, run_playbook
    from ansible_flow_mcp.security import load_policy

    if tool in {"list_collections", "list_collections_tool"}:
        return {"collections": list_collections(), "version": __version__, "role": "spoke"}
    if tool in {"search_modules", "search_modules_tool"}:
        hits = search_modules(str(arguments.get("query") or ""), limit=int(arguments.get("limit") or 25))
        return {"count": len(hits), "items": hits}
    if tool in {"get_module_schema", "get_module_schema_tool"}:
        policy = load_policy()
        fqcn = policy.assert_module_allowed(str(arguments.get("module") or ""))
        schema = get_module_schema(fqcn)
        return {"fqcn": fqcn, "schema": schema}
    if tool in {"run_module", "run_module_tool"}:
        # spoke policy forces localhost
        result = run_module(
            str(arguments.get("module") or ""),
            args=arguments.get("args"),
            hosts="localhost",
            check_mode=bool(arguments.get("check_mode", True)),
            become=bool(arguments.get("become", False)),
            become_user=arguments.get("become_user"),
            timeout=float(arguments.get("timeout") or 120),
        )
        payload = result.to_dict()
        payload["stdout"] = (payload.get("stdout") or "")[:8000]
        payload["stderr"] = (payload.get("stderr") or "")[:4000]
        return payload
    if tool in {"run_playbook", "run_playbook_tool"}:
        result = run_playbook(
            str(arguments.get("playbook") or ""),
            check_mode=bool(arguments.get("check_mode", True)),
            become=bool(arguments.get("become", False)),
            become_user=arguments.get("become_user"),
            extra_vars=arguments.get("extra_vars"),
            limit=arguments.get("limit") or "localhost",
            tags=arguments.get("tags"),
            skip_tags=arguments.get("skip_tags"),
            timeout=float(arguments.get("timeout") or 300),
        )
        payload = result.to_dict()
        payload["stdout"] = (payload.get("stdout") or "")[:8000]
        payload["stderr"] = (payload.get("stderr") or "")[:4000]
        return payload
    if tool in {"spoke_status", "status"}:
        from ansible_flow_mcp.spoke.join import spoke_status

        return spoke_status()
    raise ValueError(f"unknown spoke tool: {tool}")


def run_spoke_session() -> None:
    """ForceCommand entry: simple-exec one-shot OR full MCP stdio (localhost-only)."""
    os.environ["ANSIBLE_FLOW_ROLE"] = "spoke"
    os.environ.pop("ANSIBLE_FLOW_INVENTORY", None)

    # Peek first non-empty line without consuming a full MCP stream when possible.
    # SSH clients for spoke_call send one JSON line then EOF.
    if sys.stdin.isatty():
        from ansible_flow_mcp.server import run_server

        run_server(role="spoke")
        return

    first = ""
    while True:
        ch = sys.stdin.read(1)
        if ch == "":
            break
        if ch in "\r\n":
            if first.strip():
                break
            continue
        first += ch
        # Heuristic: simple protocol always starts with {"ansible_flow"
        if len(first) >= 16 and not first.lstrip().startswith('{"ansible_flow"'):
            # Not simple protocol — hand off remaining stream to MCP is hard once peeked.
            # For non-simple, only support simple protocol over ForceCommand in v1;
            # full agent MCP attaches on hub. Still allow local `spoke session` TTY/MCP
            # via explicit env.
            break
        if len(first) > 1_000_000:
            break

    if first.lstrip().startswith('{"ansible_flow"'):
        # read rest of first line if any
        rest = sys.stdin.readline()
        line = first + rest
        resp = _try_simple_exec_line(line.strip())
        if resp is None:
            resp = {"ok": False, "error": "invalid simple-exec request"}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()
        return

    # Fallback: full MCP stdio (dev / local). Peeked bytes are lost — only works when
    # nothing was peeked (empty) or ANSIBLE_FLOW_SPOKE_MCP=1 with fresh stdin.
    if os.environ.get("ANSIBLE_FLOW_SPOKE_MCP", "").lower() in {"1", "true", "yes"} or not first:
        from ansible_flow_mcp.server import run_server

        run_server(role="spoke")
        return

    sys.stdout.write(
        json.dumps(
            {
                "ok": False,
                "error": "spoke ForceCommand expects simple-exec JSON "
                '({"ansible_flow":1,"op":"call",...}) or set ANSIBLE_FLOW_SPOKE_MCP=1',
            }
        )
        + "\n"
    )


def main() -> None:
    run_spoke_session()
    sys.exit(0)
