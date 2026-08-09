from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ansible_flow_mcp.hub.inventory import load_inventory
from ansible_flow_mcp.hub.state import HubState, load_hub_state


@dataclass
class SpokeCallResult:
    node: str
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    payload: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "ok": self.ok,
            "exitCode": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "payload": self.payload,
        }


def _spoke_target(state: HubState, node: str) -> tuple[str, int, str]:
    """Return (host, port, mesh_user) for spoke_call ForceCommand SSH.

    Mesh user is always mcp-spoke (ForceCommand MCP). Inventory ansible_user is
    the shell account for ansible CLI (mcp-ansible) and must not be used here.
    """
    inv = load_inventory(state.inventory_path)
    children = (inv.get("all") or {}).get("children") or {}
    spokes = (children.get("spokes") or {}).get("hosts") or {}
    targets = (children.get("targets") or {}).get("hosts") or {}
    if node in targets:
        raise ValueError(
            f"{node!r} is an Ansible target (kind=target), not a mesh spoke; "
            "spoke_call requires an enrolled spoke with ForceCommand MCP"
        )
    if node not in spokes:
        raise ValueError(f"spoke {node!r} is not enrolled")
    meta = spokes[node] or {}
    host = str(meta.get("ansible_host") or node)
    port = int(meta.get("ansible_port") or 22)
    vars_n = (inv.get("all") or {}).get("vars") or {}
    user = str(
        meta.get("mesh_user")
        or vars_n.get("mesh_user")
        or "mcp-spoke"
    )
    return host, port, user


def spoke_call(
    node: str,
    *,
    tool: str = "list_collections",
    arguments: dict[str, Any] | None = None,
    state: HubState | None = None,
    root: Path | None = None,
    timeout: float = 60.0,
    remote_command: str = "ansible-flow-mcp spoke session",
) -> SpokeCallResult:
    """SSH to enrolled spoke ForceCommand MCP and run one tool via a tiny JSON-RPC handshake.

    Protocol (lab/v1): hub sends a single line JSON request on stdin of the remote
    MCP is full stdio — for v1 we use a side-channel helper mode:

      ansible-flow-mcp spoke exec --tool X --args '{...}'

    which spokes accept when invoked under ForceCommand session wrapper via env
    ANSIBLE_FLOW_SPOKE_EXEC=1, or we SSH with an explicit exec if ForceCommand
    allows only session.

    For ForceCommand-only sessions, we use MCP initialize + tools/call JSON-RPC
    over the SSH stdio channel.
    """
    st = state or load_hub_state(root)
    host, port, user = _spoke_target(st, node)
    key = st.client_key_path
    known = st.known_hosts_path

    argv = [
        "ssh",
        "-i",
        str(key),
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        f"UserKnownHostsFile={known}",
        "-o",
        "StrictHostKeyChecking=yes",
        f"{user}@{host}",
    ]
    # ForceCommand ignores remote command; omit extra for purity
    # argv stays user@host only

    # Prefer simple hub↔spoke exec protocol (one JSON line) — robust over SSH.
    # Falls back to MCP JSON-RPC NDJSON if remote only speaks MCP.
    args = arguments or {}
    simple = {
        "ansible_flow": 1,
        "op": "call",
        "tool": tool,
        "arguments": args,
    }
    stdin_data = (json.dumps(simple, separators=(",", ":")) + "\n").encode("utf-8")

    proc = subprocess.run(
        argv,
        input=stdin_data,
        capture_output=True,
        timeout=max(5.0, float(timeout)),
        check=False,
    )
    stdout = proc.stdout or b""
    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    text = stdout.decode("utf-8", errors="replace")
    payload = _parse_simple_or_mcp(text)
    ok = proc.returncode == 0 and payload is not None and not payload.get("error")
    if payload and payload.get("ok") is False:
        ok = False
    return SpokeCallResult(
        node=node,
        ok=ok,
        exit_code=proc.returncode,
        stdout=text[:8000],
        stderr=stderr[:4000],
        payload=payload,
    )


def _parse_simple_or_mcp(text: str) -> dict[str, Any] | None:
    """Parse simple exec response or last JSON object from MCP NDJSON."""
    if not text.strip():
        return None
    # Prefer last complete JSON object on its own line
    last: dict[str, Any] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last = obj
    if last is not None:
        return last
    try:
        start = text.rfind("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
    except json.JSONDecodeError:
        return None
    return None


def ssh_ping_spoke(
    node: str,
    *,
    state: HubState | None = None,
    root: Path | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Connectivity check: SSH and expect ForceCommand MCP to start (initialize)."""
    result = spoke_call(node, tool="list_collections", state=state, root=root, timeout=timeout)
    return {
        "node": node,
        "ok": result.ok,
        "exitCode": result.exit_code,
        "stderr": result.stderr[:500],
        "hasPayload": result.payload is not None,
    }
