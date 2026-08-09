from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ansible_flow_mcp.hub.state import HubState, audit_log, load_hub_state


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


@dataclass
class IssuedToken:
    token: str
    jti: str
    node_name: str
    exp: int
    hub_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "jti": self.jti,
            "node_name": self.node_name,
            "exp": self.exp,
            "exp_iso": datetime.fromtimestamp(self.exp, tz=timezone.utc).isoformat(),
            "hub_id": self.hub_id,
            "max_uses": 1,
        }


@dataclass
class TokenClaims:
    hub_id: str
    jti: str
    exp: int
    node_name: str
    v: int = 1


def _sign(payload_b64: str, key: bytes) -> str:
    sig = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64url(sig)


def issue_token(
    node_name: str,
    *,
    ttl_seconds: int = 900,
    state: HubState | None = None,
    root: Path | None = None,
) -> IssuedToken:
    st = state or load_hub_state(root)
    name = (node_name or "").strip()
    if not name or "/" in name or " " in name:
        raise ValueError("node_name must be a non-empty hostname-like token")
    ttl = max(60, min(int(ttl_seconds), 86400))
    now = int(time.time())
    jti = str(uuid.uuid4())
    claims = {
        "v": 1,
        "hub_id": st.hub_id,
        "jti": jti,
        "exp": now + ttl,
        "node_name": name,
        "max_uses": 1,
    }
    payload_b64 = _b64url(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _sign(payload_b64, st.signing_key)
    token = f"{payload_b64}.{sig}"
    audit_log(st, "issue_token", node_name=name, jti=jti, exp=claims["exp"], ttl=ttl)
    return IssuedToken(
        token=token,
        jti=jti,
        node_name=name,
        exp=int(claims["exp"]),
        hub_id=st.hub_id,
    )


def _load_replay(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    items = data.get("jti") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return set()
    return {str(x) for x in items}


def _save_replay(path: Path, jtis: set[str]) -> None:
    # keep last 10k
    ordered = sorted(jtis)[-10000:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jti": ordered}, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def verify_token(
    token: str,
    *,
    state: HubState | None = None,
    root: Path | None = None,
    consume: bool = True,
    expected_name: str | None = None,
) -> TokenClaims:
    st = state or load_hub_state(root)
    raw = (token or "").strip()
    if not raw or raw.count(".") != 1:
        raise ValueError("invalid token format")
    payload_b64, sig = raw.split(".", 1)
    expect = _sign(payload_b64, st.signing_key)
    if not hmac.compare_digest(expect, sig):
        raise ValueError("invalid token signature")
    try:
        claims = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid token payload") from exc
    if not isinstance(claims, dict):
        raise ValueError("invalid token payload")
    hub_id = str(claims.get("hub_id") or "")
    jti = str(claims.get("jti") or "")
    node_name = str(claims.get("node_name") or "")
    exp = int(claims.get("exp") or 0)
    if hub_id != st.hub_id:
        raise ValueError("token hub_id mismatch")
    if not jti or not node_name:
        raise ValueError("token missing jti/node_name")
    if exp < int(time.time()):
        raise ValueError("token expired")
    if expected_name and expected_name != node_name:
        raise ValueError(f"token node_name {node_name!r} != {expected_name!r}")

    used = _load_replay(st.replay_db_path)
    if jti in used:
        raise ValueError("token already used (replay)")
    if consume:
        used.add(jti)
        _save_replay(st.replay_db_path, used)
        audit_log(st, "token_consumed", jti=jti, node_name=node_name)

    return TokenClaims(hub_id=hub_id, jti=jti, exp=exp, node_name=node_name, v=int(claims.get("v") or 1))
