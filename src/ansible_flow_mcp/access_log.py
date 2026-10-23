"""One-line JSON access logs on stdout. Never include secret values."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

_SECRET_PARTS = ("token", "password", "secret", "authorization", "private", "cookie", "key")


def log_access(
    *,
    action: str,
    outcome: str,
    actor: str = "anonymous",
    source_ip: str = "-",
    request_id: str | None = None,
    service: str = "ansible-flow-mcp",
    **fields: Any,
) -> None:
    for name in fields:
        lowered = name.lower()
        if any(part in lowered for part in _SECRET_PARTS):
            raise ValueError(f"refusing to log field {name}")
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "service": service,
        "environment": (os.environ.get("ANSIBLE_FLOW_ENVIRONMENT") or "development").strip()
        or "development",
        "request_id": request_id or str(uuid.uuid4()),
        "actor": actor,
        "source_ip": source_ip or "-",
        "action": action,
        "outcome": outcome,
    }
    for name, value in fields.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            record[name] = value
        else:
            record[name] = str(value)
    sys.stdout.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()
