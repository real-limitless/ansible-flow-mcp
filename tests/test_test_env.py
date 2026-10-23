from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _render():
    path = ROOT / "test-env" / "scripts" / "render.py"
    spec = importlib.util.spec_from_file_location("afm_test_render", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compose_matches_flavors_and_stays_private():
    render = _render()
    text = render.render_text()
    assert text == (ROOT / "test-env" / "docker-compose.yml").read_text(encoding="utf-8")
    spec = render.load_flavors()
    assert spec["_total_mb"] <= spec["budget_mb"] <= 2048
    lowered = text.lower()
    assert "ports:" not in lowered
    for spoke in spec["spokes"]:
        assert f"container_name: afm-test-spoke-{spoke['name']}" in text
        assert f"mem_limit: {spoke['memory_mb']}m" in text
    assert "mem_limit: 640m" in text
    assert "restart: unless-stopped" in text
    assert "internal: true" in text
    assert "labels:" not in lowered
    assert "INSTALL_OPENCODE: \"0\"" in text
    assert "hub.example.com" not in text
    assert 'ANSIBLE_FLOW_PUBLIC_HOST: "${HUB_PUBLIC_HOST:-afm-test-hub}"' in text
    assert "ANSIBLE_FLOW_ADMIN_BIND: localhost" in text
    assert spec["listen_all"] == "unspecified"
    assert 'ANSIBLE_FLOW_HTTP_HOST: "unspecified"' in text
    assert "cap_drop: [ALL]" in text
    assert "FOWNER" in text
    assert "no-new-privileges:true" in text
    assert "read_only: true" in text
    assert "ports:" not in lowered
    assert "ANSIBLE_FLOW_HTTP_PORT: \"8790\"" in text
    assert "ANSIBLE_FLOW_MCP_TOKEN_FILE:" in text
    assert "ANSIBLE_FLOW_MCP_TOKEN:" not in text
    assert "ANSIBLE_FLOW_MCP_HTTP_BIND" not in text
    assert "ANSIBLE_FLOW_MCP_MAX_SESSIONS: \"32\"" in text
    assert "ANSIBLE_FLOW_MCP_RATE_PER_MINUTE: \"120\"" in text
    assert "afm-test-hub,hub" in text
    assert 'subnet: "${AFM_TEST_SUBNET:-192.0.2.0/24}"' in text
    assert "fedora:44" in text
    assert "alpine:3.24" in text
    assert "fedora:latest" not in text
    assert "alpine:3\n" not in text


def test_spoke_join_backoff_grows_and_caps():
    import random

    path = ROOT / "lab" / "images" / "retry_delay.py"
    spec = importlib.util.spec_from_file_location("afm_retry_delay", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.backoff_seconds(0, rng=random.Random(0)) == 1
    for attempt in range(0, 12):
        for seed in range(5):
            delay = module.backoff_seconds(attempt, rng=random.Random(seed))
            assert 1 <= delay <= 60
    assert module.backoff_seconds(8, rng=random.Random(1)) <= 60
    script = (ROOT / "lab" / "images" / "spoke-test-autojoin.sh").read_text(encoding="utf-8")
    assert "retry_delay.py" in script
    assert "sleep 3" not in script


def test_mcp_http_unspecified_host_is_a_string(monkeypatch: pytest.MonkeyPatch):
    import os

    from ansible_flow_mcp.cli import _hub_main, build_parser

    seen: dict[str, object] = {}

    def fake_serve_http(*, host: str = "0.0.0.0", port: int = 8789) -> None:
        seen["host"] = host
        seen["port"] = port
        os.environ["ANSIBLE_FLOW_HTTP_HOST"] = str(host)

    monkeypatch.setattr("ansible_flow_mcp.http_mcp.serve_http", fake_serve_http)
    args = build_parser().parse_args(["hub", "mcp-http", "--host", "unspecified", "--port", "8790"])
    _hub_main(args)
    assert seen["host"] == "0.0.0.0"
    assert isinstance(seen["host"], str)
    assert isinstance(os.environ["ANSIBLE_FLOW_HTTP_HOST"], str)
    assert seen["port"] == 8790


def test_serve_http_coerces_int_host_without_binding(monkeypatch: pytest.MonkeyPatch):
    import os

    import ansible_flow_mcp.http_mcp as http_mcp

    monkeypatch.setenv("ANSIBLE_FLOW_MCP_TOKEN", "file-bearer")
    monkeypatch.setenv("ANSIBLE_FLOW_ROLE", "hub")
    monkeypatch.delenv("ANSIBLE_FLOW_HTTP_BIND_SUBNETS", raising=False)

    def fake_run(*_args, **_kwargs):
        return None

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    http_mcp.serve_http(host=0, port=9)  # type: ignore[arg-type]
    assert os.environ["ANSIBLE_FLOW_HTTP_HOST"] == "0.0.0.0"
    assert isinstance(os.environ["ANSIBLE_FLOW_HTTP_HOST"], str)


def test_hub_mcp_http_is_the_shared_listener(tmp_path: Path):
    import ansible_flow_mcp.http_mcp as http_mcp
    from ansible_flow_mcp.cli import build_parser, read_supplied_token

    assert callable(http_mcp.serve_http)
    assert callable(http_mcp.load_mcp_bearer_token)
    args = build_parser().parse_args(["hub", "mcp-http", "--host", "unspecified", "--port", "8790"])
    assert args.hub_cmd == "mcp-http"
    assert args.host == "unspecified"
    assert args.port == 8790
    secret = tmp_path / "join-token"
    secret.write_text("one-time\n", encoding="utf-8")
    assert read_supplied_token(token=None, token_file=str(secret)) == "one-time"
    with pytest.raises(ValueError):
        read_supplied_token(token="abc", token_file=str(secret))
    with pytest.raises(ValueError):
        read_supplied_token(token=None, token_file=None)


def test_private_net_overlay_publishes_nothing():
    text = (ROOT / "test-env" / "docker-compose.private-net.yml").read_text(encoding="utf-8")
    assert "ports:" not in text.lower()
    assert "external: true" in text
    assert "private-network" in text
    assert "ipam:" not in text
    assert "${AFM_TEST_PRIVATE_SUBNET" not in text
    docs = (ROOT / "docs" / "TEST-ENV.md").read_text(encoding="utf-8")
    assert "AFM_TEST_SUBNET" in docs
    assert "AFM_TEST_PRIVATE_SUBNET" in docs
    assert "192.0.2.0/24" in docs
    assert "198.51.100.0/24" in docs
    assert "fedora:44" in docs
    assert "alpine:3.24" in docs
    assert "fedora:latest" not in docs
    tailnet_path = ROOT / "test-env" / "docker-compose.tailnet.yml"
    tailnet = tailnet_path.read_text(encoding="utf-8")
    assert tailnet == _render().render_tailnet()
    assert "profiles: [\"tailnet\"]" in tailnet
    assert "ports:" not in tailnet.lower()
    assert "203.0.113.0/24" in tailnet
    assert "NET_ADMIN" in tailnet
    assert "network_mode: \"service:hub\"" in tailnet
    assert "ANSIBLE_FLOW_HTTP_BIND_SUBNETS" in tailnet
    assert "AFM_TEST_TAILNET_SUBNET" not in tailnet.split("ANSIBLE_FLOW_HTTP_BIND_SUBNETS", 1)[1].split("\n", 1)[0]
