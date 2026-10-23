"""One JSON audit object per line on stdout.

Operators keep the stream for 90 days. This module never writes tokens,
secrets, or argument values.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

_OUTCOMES = {"ok", "denied", "error"}
_DROPPED = ("token", "password", "secret", "authorization", "cookie", "bearer", "args", "argument", "private")
_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")

actor_var: ContextVar[str] = ContextVar("afm_actor", default="anonymous")
client_ip_var: ContextVar[str] = ContextVar("afm_client_ip", default="-")
request_id_var: ContextVar[str] = ContextVar("afm_request_id", default="-")


def actor_from_token(token: str) -> str:
    """Stable non-secret id for the authenticated bearer. Not a client header."""
    label = (os.environ.get("ANSIBLE_FLOW_MCP_KEY_LABEL") or "").strip()
    if label:
        cleaned = _LABEL_RE.sub("", label)[:64]
        if cleaned:
            return "label:" + cleaned
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return "key:" + digest


def emit_audit(
    *,
    event: str,
    actor: str,
    client_ip: str,
    request_id: str,
    tool: str,
    outcome: str,
    duration_ms: int,
    target: str | None = None,
    **extra: Any,
) -> None:
    safe_outcome = outcome if outcome in _OUTCOMES else "error"
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
        "actor": actor or "anonymous",
        "client_ip": client_ip or "-",
        "request_id": request_id or "-",
        "tool": tool,
        "outcome": safe_outcome,
        "duration_ms": max(0, int(duration_ms)),
    }
    if target:
        record["target"] = str(target)[:128]
    for key, value in extra.items():
        lowered = key.lower()
        if any(part in lowered for part in _DROPPED):
            continue
        if isinstance(value, (dict, list)):
            continue
        record[key] = value
    sys.stdout.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()
