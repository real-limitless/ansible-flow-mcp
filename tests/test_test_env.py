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
    assert "hub.example.com" in text
    assert spec["listen_all"] == "unspecified"
    assert text.count("unspecified") >= 2
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
