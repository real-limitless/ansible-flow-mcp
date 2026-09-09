from __future__ import annotations

import json
import os
import secrets
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ansible_flow_mcp.hub.inventory import default_inventory, write_inventory
from ansible_flow_mcp.paths import ensure_dir, hub_dir


@dataclass
class HubState:
    root: Path
    hub_id: str
    name: str
    signing_key: bytes
    client_key_path: Path
    client_pub_path: Path
    known_hosts_path: Path
    inventory_path: Path
    replay_db_path: Path
    node_yml_path: Path

    def node_dict(self) -> dict[str, Any]:
        if self.node_yml_path.is_file():
            return yaml.safe_load(self.node_yml_path.read_text(encoding="utf-8")) or {}
        return {"name": self.name, "hub_id": self.hub_id, "role": "hub"}


def _run_ssh_keygen(path: Path, comment: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    subprocess.run(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            comment,
            "-f",
            str(path),
            "-q",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    os.chmod(path, 0o600)
    pub = Path(str(path) + ".pub")
    if pub.is_file():
        os.chmod(pub, 0o644)


def hub_init(
    name: str = "hub-01",
    *,
    root: Path | None = None,
    force: bool = False,
) -> HubState:
    base = ensure_dir(root or hub_dir())
    hub_id_path = base / "hub_id"
    if hub_id_path.is_file() and not force:
        return load_hub_state(base)

    hub_id = str(uuid.uuid4())
    signing_key = secrets.token_bytes(32)

    keys = ensure_dir(base / "keys")
    ca = ensure_dir(base / "ca")
    tokens = ensure_dir(base / "tokens")
    ensure_dir(base / "sshd")

    client_key = keys / "hub_client"
    _run_ssh_keygen(client_key, f"ansible-flow-hub-client@{name}")

    # Separate ansible client key (may equal hop key in lab; split paths for prod)
    ansible_key = keys / "ansible_client"
    _run_ssh_keygen(ansible_key, f"ansible-flow-ansible@{name}")

    signing_path = ca / "signing.key"
    signing_path.write_bytes(signing_key)
    os.chmod(signing_path, 0o600)

    hub_id_path.write_text(hub_id + "\n", encoding="utf-8")
    os.chmod(hub_id_path, 0o644)

    node = {
        "name": name,
        "hub_id": hub_id,
        "role": "hub",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ansible_user": "mcp-ansible",
    }
    node_path = base / "node.yml"
    node_path.write_text(yaml.safe_dump(node, sort_keys=False), encoding="utf-8")
    os.chmod(node_path, 0o600)

    from ansible_flow_mcp.hub.inventory import set_ansible_key_vars

    inv = default_inventory(hub_name=name)
    set_ansible_key_vars(inv, ansible_key)
    # known_hosts path for ansible
    inv.setdefault("all", {}).setdefault("vars", {})
    inv["all"]["vars"]["ansible_ssh_common_args"] = (
        f"-o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o BatchMode=yes "
        f"-o UserKnownHostsFile={base / 'known_hosts'}"
    )
    write_inventory(base / "inventory.yml", inv)

    known = base / "known_hosts"
    if not known.exists():
        known.write_text("", encoding="utf-8")
        os.chmod(known, 0o660)

    replay = tokens / "replay.db"
    if not replay.exists():
        replay.write_text(json.dumps({"jti": []}, indent=2) + "\n", encoding="utf-8")
        os.chmod(replay, 0o660)

    audit = base / "audit.jsonl"
    if not audit.exists():
        audit.write_text("", encoding="utf-8")
        os.chmod(audit, 0o600)

    ensure_admin_token(base)

    return load_hub_state(base)


def load_hub_state(root: Path | None = None) -> HubState:
    base = Path(root or hub_dir()).expanduser().resolve()
    hub_id_path = base / "hub_id"
    if not hub_id_path.is_file():
        raise FileNotFoundError(f"hub not initialized at {base} (missing hub_id)")

    hub_id = hub_id_path.read_text(encoding="utf-8").strip()
    node_path = base / "node.yml"
    name = "hub"
    if node_path.is_file():
        node = yaml.safe_load(node_path.read_text(encoding="utf-8")) or {}
        name = str(node.get("name") or name)

    signing_path = base / "ca" / "signing.key"
    if not signing_path.is_file():
        raise FileNotFoundError(f"missing signing key: {signing_path}")
    signing_key = signing_path.read_bytes()

    client_key = base / "keys" / "hub_client"
    client_pub = Path(str(client_key) + ".pub")
    if not client_key.is_file():
        raise FileNotFoundError(f"missing hub client key: {client_key}")

    return HubState(
        root=base,
        hub_id=hub_id,
        name=name,
        signing_key=signing_key,
        client_key_path=client_key,
        client_pub_path=client_pub,
        known_hosts_path=base / "known_hosts",
        inventory_path=base / "inventory.yml",
        replay_db_path=base / "tokens" / "replay.db",
        node_yml_path=node_path,
    )


ADMIN_TOKEN_FILENAME = "admin.token"
_REDACT_KEY_SUBSTR = ("password", "secret", "token", "private_key")


def admin_token_path(root: Path) -> Path:
    return Path(root).expanduser().resolve() / ADMIN_TOKEN_FILENAME


def ensure_admin_token(root: Path) -> Path:
    """Create `$HUB_DIR/admin.token` (0600) if missing. Never logs the value."""
    path = admin_token_path(root)
    if path.is_file() and path.stat().st_size > 0:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def load_admin_token(root: Path) -> str:
    """Env `ANSIBLE_FLOW_ADMIN_TOKEN` wins; else file (created if missing)."""
    env = (os.environ.get("ANSIBLE_FLOW_ADMIN_TOKEN") or "").strip()
    if env:
        return env
    path = ensure_admin_token(root)
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        path.unlink(missing_ok=True)
        path = ensure_admin_token(root)
        token = path.read_text(encoding="utf-8").strip()
    return token


def _redact_audit_value(key: str, value: Any) -> Any:
    lk = str(key).lower()
    if any(part in lk for part in _REDACT_KEY_SUBSTR):
        return "********"
    if isinstance(value, dict):
        return {k: _redact_audit_value(k, v) for k, v in value.items()}
    return value


def redact_audit_record(record: dict[str, Any]) -> dict[str, Any]:
    return {k: _redact_audit_value(k, v) for k, v in record.items()}


def audit_log(state: HubState, event: str, **fields: Any) -> None:
    path = state.root / "audit.jsonl"
    record = redact_audit_record(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read_audit(
    state: HubState | None = None,
    *,
    root: Path | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    st = state or load_hub_state(root)
    path = st.root / "audit.jsonl"
    if not path.is_file():
        return []
    cap = max(1, min(int(limit), 1000))
    recs: list[dict[str, Any]] = []
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            recs.append(redact_audit_record(raw))
        if len(recs) >= cap:
            break
    return recs
