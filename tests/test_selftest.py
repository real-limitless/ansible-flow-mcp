from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _selftest():
    path = ROOT / "test-env" / "scripts" / "selftest.py"
    spec = importlib.util.spec_from_file_location("afm_selftest", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summary_pass_fail_and_redaction():
    mod = _selftest()
    text, code = mod.summarize(
        ["debian", "alpine"],
        health_ok=True,
        init_ok=True,
        enrolled={"debian", "alpine"},
        reachable={"debian"},
    )
    assert code == 1
    assert "debian PASS" in text
    assert "alpine FAIL unreachable" in text
    assert text.endswith("overall FAIL\n")
    secret = "lab-bearer-do-not-print"
    assert secret not in mod.safe_text(f"nope {secret}", secret)


def test_selftest_check_hides_token():
    token = "lab-bearer-do-not-print"
    mod = _selftest()
    seen: list[str] = []

    def http(method, url, headers, body):
        seen.append(headers.get("Authorization", ""))
        if method == "GET":
            return 200, {}, '{"ok": true}'
        raw = body.decode() if body else ""
        if "initialize" in raw and "notifications" not in raw:
            return 200, {"mcp-session-id": "sess"}, '{"result":{"protocolVersion":"2025-03-26"}}'
        if "hub_status" in raw:
            payload = json.dumps({"spokes": []})
            event = json.dumps(
                {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": payload}], "isError": False}}
            )
            return 200, {}, "event: message\ndata: " + event + "\n"
        return 202, {}, ""

    text, code = mod.check_once(
        ["debian"],
        base="http://afm-test-hub:8790",
        token=token,
        http=http,
        connect=lambda _name: True,
    )
    assert code == 1
    assert "hub-health PASS" in text
    assert "hub-initialize PASS" in text
    assert "debian FAIL not enrolled" in text
    assert token not in text
    assert any(header == "Bearer " + token for header in seen)
    assert mod.safe_text("\n".join(seen), token).count(token) == 0


def test_spokes_parser_rejects_tool_error():
    mod = _selftest()
    body = 'event: message\ndata: ' + json.dumps(
        {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "nope"}], "isError": True}}
    )
    assert mod.spokes_from_body(body) is None
    ok = 'data: ' + json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps({"spokes": ["debian"]})}], "isError": False},
        }
    )
    assert mod.spokes_from_body(ok) == ["debian"]
