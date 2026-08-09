from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from ansible_flow_mcp.paths import ensure_dir, spoke_dir

JoinTransport = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass
class SpokeState:
    root: Path
    name: str
    hub: str
    hub_id: str
    role: str = "spoke"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "hub": self.hub,
            "hub_id": self.hub_id,
            "role": self.role,
        }


def _parse_hub(hub: str) -> tuple[str, str, int]:
    """Return (user, host, port) from user@host:port."""
    text = (hub or "").strip()
    if not text:
        raise ValueError("hub is required (user@host[:port])")
    user = "mcp-join"
    hostport = text
    if "@" in text:
        user, hostport = text.split("@", 1)
    port = 22
    host = hostport
    if hostport.startswith("["):
        # [ipv6]:port
        end = hostport.find("]")
        host = hostport[1:end]
        rest = hostport[end + 1 :]
        if rest.startswith(":"):
            port = int(rest[1:])
    elif ":" in hostport:
        host, p = hostport.rsplit(":", 1)
        if p.isdigit():
            port = int(p)
        else:
            host = hostport
    return user, host, port


def _ssh_join_transport(
    hub: str,
    payload: dict[str, Any],
    *,
    identity: Path | None = None,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    user, host, port = _parse_hub(hub)
    argv = [
        "ssh",
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "IdentitiesOnly=yes",
    ]
    if identity is not None and identity.is_file():
        argv.extend(["-i", str(identity)])
    if extra_args:
        argv.extend(extra_args)
    argv.append(f"{user}@{host}")
    # ForceCommand on hub runs accept-join; still pass as remote cmd for clarity
    argv.append("ansible-flow-mcp hub accept-join")

    proc = subprocess.run(
        argv,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 and not out:
        raise RuntimeError(f"join ssh failed rc={proc.returncode}: {proc.stderr[:2000]}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid join response: {out[:500]}") from exc
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or data.get("message") or "join rejected")
    return data


def _read_host_pubkey() -> str:
    candidates = [
        Path("/etc/ssh/ssh_host_ed25519_key.pub"),
        Path("/etc/ssh/ssh_host_rsa_key.pub"),
        Path("/etc/ssh/ssh_host_ecdsa_key.pub"),
    ]
    for p in candidates:
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return ""


def _install_authorized_key(
    *,
    pubkey: str,
    force_command: str | None,
    auth_keys_path: Path,
) -> None:
    """Install a pubkey. force_command=None → plain key (ansible shell user)."""
    ensure_dir(auth_keys_path.parent, 0o700)
    pub = pubkey.strip()
    if not pub:
        return
    if force_command:
        opts = (
            f'command="{force_command}",no-port-forwarding,no-X11-forwarding,'
            "no-agent-forwarding,no-pty"
        )
        line = f"{opts} {pub}\n"
    else:
        # Ansible needs a real shell — never ForceCommand MCP on this key
        line = f"no-port-forwarding,no-X11-forwarding,no-agent-forwarding {pub}\n"
    existing = auth_keys_path.read_text(encoding="utf-8") if auth_keys_path.is_file() else ""
    key_body = pub.split()[-1] if pub else ""
    lines = [ln for ln in existing.splitlines(True) if key_body not in ln]
    lines.append(line)
    auth_keys_path.write_text("".join(lines), encoding="utf-8")
    os.chmod(auth_keys_path, 0o600)


def spoke_join(
    *,
    token: str,
    hub: str,
    public_addr: str,
    node_name: str | None = None,
    ssh_port: int = 22,
    root: Path | None = None,
    transport: JoinTransport | None = None,
    identity: Path | None = None,
    auth_keys_path: Path | None = None,
    force_command: str | None = None,
) -> dict[str, Any]:
    base = ensure_dir(root or spoke_dir())
    ensure_dir(base / "keys")

    # derive name from token payload if not provided (without verifying sig here)
    name = (node_name or "").strip()
    if not name:
        try:
            import base64

            payload_b64 = token.strip().split(".", 1)[0]
            pad = "=" * (-len(payload_b64) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
            name = str(claims.get("node_name") or "")
        except Exception as exc:  # noqa: BLE001
            raise ValueError("node_name required (could not parse token)") from exc
    if not name:
        raise ValueError("node_name required")

    ansible_user = (
        os.environ.get("ANSIBLE_FLOW_ANSIBLE_USER") or "mcp-ansible"
    ).strip() or "mcp-ansible"
    mesh_user = (
        os.environ.get("ANSIBLE_FLOW_MESH_USER") or "mcp-spoke"
    ).strip() or "mcp-spoke"

    host_pubkey = _read_host_pubkey()
    payload = {
        "token": token,
        "node_name": name,
        "public_addr": public_addr,
        "ssh_port": int(ssh_port),
        "host_pubkey": host_pubkey,
        "ansible_user": ansible_user,
    }

    tr = transport or (
        lambda _hub, body: _ssh_join_transport(_hub, body, identity=identity)
    )
    resp = tr(hub, payload)

    fc = force_command or str(resp.get("force_command") or "/usr/local/bin/ansible-flow-mcp spoke session")
    hub_pub = str(resp.get("hub_client_pubkey") or "").strip()
    if not hub_pub:
        raise RuntimeError("hub did not return hub_client_pubkey")
    ansible_pub = str(resp.get("ansible_client_pubkey") or "").strip() or hub_pub
    ansible_user = str(resp.get("ansible_user") or ansible_user).strip() or ansible_user

    # Mesh channel: mcp-spoke authorized_keys WITH ForceCommand (spoke_call only)
    ak = auth_keys_path
    if ak is None:
        home = Path(os.environ.get("HOME") or f"/home/{mesh_user}")
        env_ak = os.environ.get("ANSIBLE_FLOW_SPOKE_AUTHORIZED_KEYS")
        ak = Path(env_ak) if env_ak else (base / "keys" / "authorized_keys")
        ssh_ak = home / ".ssh" / "authorized_keys"
        if home.is_dir():
            ak = ssh_ak

    _install_authorized_key(pubkey=hub_pub, force_command=fc, auth_keys_path=ak)

    # Ansible channel: plain key on shell user (no ForceCommand — ansible needs /bin/sh)
    ansible_ak_env = os.environ.get("ANSIBLE_FLOW_ANSIBLE_AUTHORIZED_KEYS")
    if ansible_ak_env:
        ansible_ak = Path(ansible_ak_env)
    else:
        ansible_home = Path(f"/home/{ansible_user}")
        if ansible_home.is_dir():
            ansible_ak = ansible_home / ".ssh" / "authorized_keys"
        else:
            ansible_ak = base / "keys" / "ansible_authorized_keys"
    _install_authorized_key(
        pubkey=ansible_pub,
        force_command=None,
        auth_keys_path=ansible_ak,
    )

    (base / "keys" / "hub_client.pub").write_text(hub_pub + "\n", encoding="utf-8")
    (base / "keys" / "ansible_client.pub").write_text(ansible_pub + "\n", encoding="utf-8")

    node = {
        "name": name,
        "role": "spoke",
        "hub": hub,
        "hub_id": resp.get("hub_id"),
        "hub_name": resp.get("hub_name"),
        "public_addr": public_addr,
        "ssh_port": int(ssh_port),
        "joined_at": datetime.now(timezone.utc).isoformat(),
        "force_command": fc,
        "mesh_user": mesh_user,
        "ansible_user": ansible_user,
        "mesh_authorized_keys": str(ak),
        "ansible_authorized_keys": str(ansible_ak),
    }
    node_path = base / "node.yml"
    node_path.write_text(yaml.safe_dump(node, sort_keys=False), encoding="utf-8")
    os.chmod(node_path, 0o600)

    redacted = {
        k: v
        for k, v in resp.items()
        if k not in {"hub_client_pubkey", "ansible_client_pubkey"}
    }
    redacted["hub_client_pubkey"] = hub_pub[:40] + "…"
    redacted["ansible_client_pubkey"] = ansible_pub[:40] + "…"

    return {
        "ok": True,
        "node": node,
        "authorized_keys": str(ak),
        "ansible_authorized_keys": str(ansible_ak),
        "hub_response": redacted,
    }


def spoke_status(*, root: Path | None = None) -> dict[str, Any]:
    base = Path(root or spoke_dir())
    node_path = base / "node.yml"
    if not node_path.is_file():
        return {"role": "spoke", "enrolled": False, "root": str(base)}
    node = yaml.safe_load(node_path.read_text(encoding="utf-8")) or {}
    return {"role": "spoke", "enrolled": True, "root": str(base), "node": node}


def write_join_stub_for_tests(tmp: Path) -> Path:
    """Helper for unit tests — not used in production."""
    ensure_dir(tmp)
    return tmp
