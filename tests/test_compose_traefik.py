"""Traefik overlay must not ask Compose to create a project network."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "deploy" / "compose.traefik.yml"
BASE = ROOT / "docker-compose.yml"


class _Loader(yaml.SafeLoader):
    pass


def _construct_override(loader: yaml.SafeLoader, node: yaml.Node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_Loader.add_constructor("!override", _construct_override)


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)


def test_overlay_replaces_networks_with_external_only():
    text = OVERLAY.read_text(encoding="utf-8")
    assert "!override" in text
    doc = _load(OVERLAY)
    service_nets = doc["services"]["ansible-flow-mcp"]["networks"]
    assert service_nets == ["dokploy-network"]
    assert "default" not in doc["networks"]
    external = doc["networks"]["dokploy-network"]
    assert external["external"] is True
    assert external["name"] == "${DOKPLOY_NETWORK:-dokploy-network}"


def test_base_compose_does_not_pin_networks():
    doc = _load(BASE)
    assert "networks" not in doc
    assert "networks" not in doc["services"]["ansible-flow-mcp"]


def _compose_version_at_least(text: str, minimum: tuple[int, int, int]) -> bool:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if match is None:
        return False
    found = tuple(int(part) for part in match.groups())
    return found >= minimum


def _compose_cmd() -> list[str] | None:
    candidates: list[list[str]] = []
    docker = shutil.which("docker")
    if docker:
        candidates.append([docker, "compose"])
    for path in (
        shutil.which("docker-compose"),
        os.path.expanduser("~/.local/bin/docker-compose"),
    ):
        if path and Path(path).is_file() and os.access(path, os.X_OK):
            candidates.append([path])
    for cmd in candidates:
        proc = subprocess.run(
            [*cmd, "version", "--short"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and _compose_version_at_least(proc.stdout, (2, 24, 0)):
            return cmd
    return None


def test_compose_config_drops_project_default_network():
    compose = _compose_cmd()
    if compose is None:
        pytest.skip("docker compose 2.24+ is not installed")
    env = os.environ.copy()
    env["DOKPLOY_NETWORK"] = "shared-proxy"
    proc = subprocess.run(
        [
            *compose,
            "-f",
            str(BASE),
            "-f",
            str(OVERLAY),
            "config",
            "--format",
            "yaml",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = yaml.safe_load(proc.stdout)
    service_nets = rendered["services"]["ansible-flow-mcp"]["networks"]
    assert list(service_nets) == ["dokploy-network"]
    assert "default" not in rendered["networks"]
    net = rendered["networks"]["dokploy-network"]
    assert net["external"] is True
    assert net["name"] == "shared-proxy"

    base_proc = subprocess.run(
        [*compose, "-f", str(BASE), "config", "--format", "yaml"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    base_rendered = yaml.safe_load(base_proc.stdout)
    assert "default" in base_rendered["networks"]
    assert base_rendered["networks"]["default"].get("external") is not True
