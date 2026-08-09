from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ansible_flow_mcp.hub.inventory import (
    add_spoke,
    load_inventory,
    remove_spoke,
    set_ansible_key_vars,
    write_inventory,
)
from ansible_flow_mcp.hub.state import HubState, audit_log, load_hub_state
from ansible_flow_mcp.hub.tokens import verify_token


@dataclass
class JoinRequest:
    token: str
    node_name: str
    public_addr: str
    ssh_port: int = 22
    host_pubkey: str = ""
    ansible_user: str = "mcp-spoke"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JoinRequest:
        return cls(
            token=str(data.get("token") or ""),
            node_name=str(data.get("node_name") or data.get("name") or ""),
            public_addr=str(data.get("public_addr") or data.get("ansible_host") or ""),
            ssh_port=int(data.get("ssh_port") or data.get("port") or 22),
            host_pubkey=str(data.get("host_pubkey") or "").strip(),
            ansible_user=str(data.get("ansible_user") or "mcp-spoke"),
        )


@dataclass
class JoinResponse:
    ok: bool
    node_name: str
    hub_id: str
    hub_name: str
    hub_client_pubkey: str
    force_command: str
    ansible_user: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "node_name": self.node_name,
            "hub_id": self.hub_id,
            "hub_name": self.hub_name,
            "hub_client_pubkey": self.hub_client_pubkey,
            "force_command": self.force_command,
            "ansible_user": self.ansible_user,
            "message": self.message,
        }


def accept_join(
    req: JoinRequest,
    *,
    state: HubState | None = None,
    root: Path | None = None,
    force_command: str = "/usr/local/bin/ansible-flow-mcp spoke session",
) -> JoinResponse:
    st = state or load_hub_state(root)
    claims = verify_token(req.token, state=st, consume=True, expected_name=req.node_name or None)
    node_name = claims.node_name
    if not req.public_addr:
        raise ValueError("public_addr is required")

    inv = load_inventory(st.inventory_path)
    set_ansible_key_vars(inv, st.root / "keys" / "ansible_client")
    add_spoke(
        inv,
        name=node_name,
        ansible_host=req.public_addr,
        ansible_port=req.ssh_port,
        ansible_user=req.ansible_user,
        extra={"mesh_enrolled": True},
    )
    write_inventory(st.inventory_path, inv)

    if req.host_pubkey:
        try:
            _append_known_host(st.known_hosts_path, req.public_addr, req.ssh_port, req.host_pubkey)
        except OSError:
            # non-fatal: operator/lab can ssh-keyscan later
            audit_log(st, "known_hosts_write_failed", node_name=node_name)

    pub = st.client_pub_path.read_text(encoding="utf-8").strip()
    # also expose ansible client pub (lab may use hub_client for both)
    audit_log(
        st,
        "accept_join",
        node_name=node_name,
        public_addr=req.public_addr,
        ssh_port=req.ssh_port,
        jti=claims.jti,
    )
    return JoinResponse(
        ok=True,
        node_name=node_name,
        hub_id=st.hub_id,
        hub_name=st.name,
        hub_client_pubkey=pub,
        force_command=force_command,
        ansible_user=req.ansible_user,
        message="enrolled",
    )


def revoke_node(
    name: str,
    *,
    state: HubState | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    st = state or load_hub_state(root)
    inv = load_inventory(st.inventory_path)
    removed = remove_spoke(inv, name)
    if removed:
        write_inventory(st.inventory_path, inv)
    # mark revoked list
    revoked_path = st.root / "tokens" / "revoked.json"
    revoked: list[str] = []
    if revoked_path.is_file():
        try:
            data = json.loads(revoked_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                revoked = [str(x) for x in data]
        except json.JSONDecodeError:
            pass
    if name not in revoked:
        revoked.append(name)
        revoked_path.write_text(json.dumps(revoked, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(revoked_path, 0o600)
        except OSError:
            pass
    audit_log(st, "revoke_node", node_name=name, removed=removed)
    return {"ok": True, "node_name": name, "removed_from_inventory": removed}


def hub_status(*, state: HubState | None = None, root: Path | None = None) -> dict[str, Any]:
    st = state or load_hub_state(root)
    inv = load_inventory(st.inventory_path)
    from ansible_flow_mcp.hub.inventory import list_spoke_names

    return {
        "role": "hub",
        "hub_id": st.hub_id,
        "name": st.name,
        "root": str(st.root),
        "spokes": list_spoke_names(inv),
        "inventory": str(st.inventory_path),
        "known_hosts": str(st.known_hosts_path),
    }


def accept_join_stdio() -> int:
    """ForceCommand entry: read one JSON object from stdin, write JSON to stdout."""
    try:
        # Ensure hub role paths resolve under ForceCommand
        os.environ.setdefault("ANSIBLE_FLOW_ROLE", "hub")
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            raise ValueError("join request must be a JSON object")
        req = JoinRequest.from_dict(data)
        if not req.node_name and req.token:
            pass
        resp = accept_join(req)
        sys.stdout.write(json.dumps(resp.to_dict(), indent=2) + "\n")
        return 0
    except Exception as exc:  # noqa: BLE001 — boundary for ForceCommand
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}) + "\n")
        return 1


def _append_known_host(path: Path, host: str, port: int, pubkey_line: str) -> None:
    line = pubkey_line.strip()
    if not line:
        return
    # OpenSSH known_hosts: [host]:port keytype key
    parts = line.split()
    if len(parts) < 2:
        return
    if parts[0].startswith("ssh-") or parts[0].startswith("ecdsa-") or parts[0].startswith("rsa-"):
        keytype, key = parts[0], parts[1]
    elif len(parts) >= 3:
        # already host keytype key
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return
    else:
        return
    marker = f"[{host}]:{port}" if port != 22 else host
    entry = f"{marker} {keytype} {key}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if key in existing and marker in existing:
        return
    if not path.exists():
        path.write_text("", encoding="utf-8")
        try:
            os.chmod(path, 0o660)
        except OSError:
            pass
    with path.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    try:
        os.chmod(path, 0o660)
    except OSError:
        pass
