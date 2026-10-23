from __future__ import annotations

import importlib.util
from pathlib import Path

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
    assert "traefik" not in lowered
    for spoke in spec["spokes"]:
        assert f"container_name: afm-test-spoke-{spoke['name']}" in text
        assert f"mem_limit: {spoke['memory_mb']}m" in text
    assert "mem_limit: 640m" in text
    assert "restart: unless-stopped" in text
    assert "internal: true" in text
    assert "labels:" not in lowered
    assert "INSTALL_OPENCODE: \"0\"" in text
    assert "hub.example.com" in text
    # The only dotted address is the unspecified in-container listen value.
    assert text.count(spec["listen_all"]) >= 2


def test_private_net_overlay_publishes_nothing():
    text = (ROOT / "test-env" / "docker-compose.private-net.yml").read_text(encoding="utf-8")
    assert "ports:" not in text.lower()
    assert "external: true" in text
    assert "private-network" in text
