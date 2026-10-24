"""One-shot connectivity check for the private lab.

Runs inside the selftest compose service. Prints one pass/fail line per
flavor and exits 0 only when every check passed. The bearer is never written.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


def json_payloads(text: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for line in text.splitlines():
        raw = line.strip()
        if raw.startswith("data:"):
            raw = raw[5:].strip()
        if not raw.startswith("{"):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            found.append(obj)
    if not found:
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(obj, dict):
            found.append(obj)
    return found


def spokes_from_body(text: str) -> list[str] | None:
    """Spoke names from a hub_status tool response. None when the call failed."""
    for obj in reversed(json_payloads(text)):
        result = obj.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("isError"):
            return None
        content = result.get("content") or []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            try:
                payload = json.loads(str(block.get("text") or ""))
            except json.JSONDecodeError:
                return None
            if isinstance(payload, dict):
                return [str(name) for name in (payload.get("spokes") or [])]
    return None


def summarize(
    names: list[str],
    *,
    health_ok: bool,
    init_ok: bool,
    enrolled: set[str],
    reachable: set[str],
) -> tuple[str, int]:
    lines = [
        f"hub-health {'PASS' if health_ok else 'FAIL'}",
        f"hub-initialize {'PASS' if init_ok else 'FAIL'}",
    ]
    failed = not health_ok or not init_ok
    for name in names:
        if not health_ok or not init_ok:
            lines.append(f"{name} FAIL hub")
            failed = True
            continue
        if name in enrolled and name in reachable:
            lines.append(f"{name} PASS")
            continue
        failed = True
        why: list[str] = []
        if name not in enrolled:
            why.append("not enrolled")
        if name not in reachable:
            why.append("unreachable")
        lines.append(f"{name} FAIL {' '.join(why)}")
    lines.append("overall " + ("PASS" if not failed else "FAIL"))
    return "\n".join(lines) + "\n", (0 if not failed else 1)


def safe_text(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text


Http = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, str], str]]


def _headers(token: str, session: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": "Bearer " + token,
    }
    if session:
        headers["mcp-session-id"] = session
    return headers


def list_spokes(http: Http, base: str, token: str) -> tuple[bool, list[str]]:
    """initialize, then hub_status. The token is a header, not part of the result."""
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "afm-selftest", "version": "0"},
        },
    }
    status, headers, body = http("POST", base + "/mcp", _headers(token), json.dumps(init).encode())
    if status != 200 or "protocolVersion" not in body:
        return False, []
    session = ""
    for key, value in headers.items():
        if key.lower() == "mcp-session-id":
            session = value
            break
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    http("POST", base + "/mcp", _headers(token, session or None), json.dumps(note).encode())
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "hub_status", "arguments": {}},
    }
    status, _headers_out, body = http(
        "POST", base + "/mcp", _headers(token, session or None), json.dumps(call).encode()
    )
    if status != 200:
        return False, []
    names = spokes_from_body(body)
    if names is None:
        return False, []
    return True, names


def check_once(
    names: list[str],
    *,
    base: str,
    token: str,
    http: Http,
    connect: Callable[[str], bool],
) -> tuple[str, int]:
    status, _headers_out, _body = http("GET", base + "/health", {}, None)
    health_ok = status == 200
    init_ok = False
    enrolled: list[str] = []
    if health_ok:
        init_ok, enrolled = list_spokes(http, base, token)
    reachable = {name for name in names if connect(name)} if init_ok else set()
    return summarize(
        names,
        health_ok=health_ok,
        init_ok=init_ok,
        enrolled=set(enrolled),
        reachable=reachable,
    )


def _urllib_http(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, {k.lower(): v for k, v in response.headers.items()}, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, raw


def _tcp_ok(name: str) -> bool:
    try:
        sock = socket.create_connection((name, 22), 5)
    except OSError:
        return False
    sock.close()
    return True


def main() -> int:
    path = Path(os.environ.get("ANSIBLE_FLOW_SELFTEST_TOKEN") or "/run/selftest-token/token")
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if not token:
        sys.stdout.write("hub-token FAIL\noverall FAIL\n")
        return 1
    base = (os.environ.get("ANSIBLE_FLOW_SELFTEST_URL") or "http://afm-test-hub:8790").rstrip("/")
    names = [part for part in (os.environ.get("ANSIBLE_FLOW_TEST_SPOKES") or "").split() if part]
    try:
        deadline = max(1, int(os.environ.get("ANSIBLE_FLOW_SELFTEST_DEADLINE") or "180"))
    except ValueError:
        deadline = 180
    started = time.monotonic()
    report = "overall FAIL\n"
    code = 1
    while True:
        try:
            report, code = check_once(names, base=base, token=token, http=_urllib_http, connect=_tcp_ok)
        except OSError:
            report, code = summarize(names, health_ok=False, init_ok=False, enrolled=set(), reachable=set())
        if code == 0 or time.monotonic() - started >= deadline:
            break
        time.sleep(5)
    sys.stdout.write(safe_text(report, token))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
