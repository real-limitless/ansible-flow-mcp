#!/usr/bin/env python3
"""Render test-env/docker-compose.yml from flavors.yml. Stdlib plus PyYAML."""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML is required (install the project, or pip install pyyaml)\n")
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parents[1]
FLAVORS = ROOT / "flavors.yml"
COMPOSE = ROOT / "docker-compose.yml"
TAILNET = ROOT / "docker-compose.tailnet.yml"
FAMILIES = {"debian", "ubuntu", "rocky", "fedora", "alpine", "rhel"}
RESERVED_GROUPS = {"all", "hub", "spokes", "targets", "ungrouped"}
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._:/-]{0,80}$")


def load_flavors(path: Path | None = None) -> dict:
    data = yaml.safe_load((path or FLAVORS).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("flavors.yml must be a mapping")
    spokes = data.get("spokes") or []
    if not isinstance(spokes, list) or not spokes:
        raise SystemExit("flavors.yml needs at least one spoke")
    names = []
    for spoke in spokes:
        name = str(spoke.get("name") or "")
        family = str(spoke.get("family") or "")
        base = str(spoke.get("base") or "")
        if not NAME_RE.match(name):
            raise SystemExit(f"invalid spoke name: {name!r}")
        if family not in FAMILIES:
            raise SystemExit(f"unsupported family for {name}: {family}")
        if not IMAGE_RE.match(base):
            raise SystemExit(f"invalid base image for {name}: {base!r}")
        mem = int(spoke.get("memory_mb") or 0)
        if mem < 64:
            raise SystemExit(f"memory_mb for {name} must be >= 64")
        names.append(name)
    if len(names) != len(set(names)):
        raise SystemExit("duplicate spoke names")
    hub = data.get("hub") or {}
    hub_mem = int(hub.get("memory_mb") or 0)
    if hub_mem < 128:
        raise SystemExit("hub memory_mb must be >= 128")
    budget = int(data.get("budget_mb") or 0)
    total = hub_mem + sum(int(s["memory_mb"]) for s in spokes)
    if total > budget:
        raise SystemExit(f"memory sum {total} exceeds budget_mb {budget}")
    group = str(data.get("seed_group") or "")
    if group and (not NAME_RE.match(group) or group in RESERVED_GROUPS):
        raise SystemExit(f"invalid seed_group: {group}")
    listen = str(data.get("listen_all") or "unspecified")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,40}", listen):
        raise SystemExit("listen_all must be a word such as unspecified")
    data["listen_all"] = listen
    data["_total_mb"] = total
    return data


def _mem(mb: int) -> str:
    return f"{int(mb)}m"


def _harden(*homes: str) -> list[str]:
    """sshd caps only. Everything else is dropped."""
    lines = [
        "    cap_drop: [ALL]",
        "    cap_add:",
        "      - NET_BIND_SERVICE",
        "      - SETUID",
        "      - SETGID",
        "      - CHOWN",
        "      - FOWNER",
        "      - DAC_OVERRIDE",
        "      - SYS_CHROOT",
        "      - AUDIT_WRITE",
        "    security_opt:",
        "      - no-new-privileges:true",
        "    read_only: true",
        "    tmpfs:",
        "      - /tmp:size=64m,mode=1777",
        "      - /run:size=32m,mode=755",
        "      - /root:size=16m,mode=700",
    ]
    for home in homes:
        lines.append(f"      - {home}:size=16m,mode=755")
    return lines


def render_tailnet() -> str:
    """Optional profile. Does not publish host ports or add router labels."""
    return "\n".join(
        [
            "# Optional remote admin. Include this file and the profile together:",
            "#   docker compose -f test-env/docker-compose.yml \\",
            "#     -f test-env/docker-compose.tailnet.yml --profile tailnet up -d",
            "# The sidecar shares the hub network namespace so it can open the",
            "# admin port on localhost. The egress network exists only so the",
            "# tailnet client can reach its coordination servers. MCP does not bind",
            "# that network: ANSIBLE_FLOW_HTTP_BIND_SUBNETS is loopback plus the lab",
            "# subnet, and the private subnet only when AFM_TEST_PRIVATE_SUBNET is set.",
            "# 203.0.113.0/24 is an RFC 5737 placeholder. Override AFM_TEST_TAILNET_SUBNET.",
            "# Set AFM_TEST_TAILNET_IMAGE to the client image. The auth key is a",
            "# file path (AFM_TEST_TAILNET_AUTHKEY_FILE), never a value in this file.",
            "services:",
            "  hub:",
            "    networks:",
            "      - afm-test",
            "      - tailnet-egress",
            "    environment:",
            "      ANSIBLE_FLOW_HTTP_BIND_SUBNETS: \"${AFM_TEST_SUBNET:-192.0.2.0/24}${AFM_TEST_PRIVATE_SUBNET:+,${AFM_TEST_PRIVATE_SUBNET}}\"",
            "  tailnet:",
            "    profiles: [\"tailnet\"]",
            "    image: ${AFM_TEST_TAILNET_IMAGE:-tailnet-client:local}",
            "    restart: unless-stopped",
            "    network_mode: \"service:hub\"",
            "    depends_on:",
            "      - hub",
            "    cap_drop: [ALL]",
            "    cap_add:",
            "      - NET_ADMIN",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    read_only: true",
            "    tmpfs:",
            "      - /tmp:size=16m,mode=1777",
            "      - /run:size=16m,mode=755",
            "    environment:",
            "      TAILNET_AUTHKEY_FILE: /run/secrets/tailnet-authkey",
            "    volumes:",
            "      - ${AFM_TEST_TAILNET_AUTHKEY_FILE:-/var/lib/ansible-flow/hub/tailnet-authkey}:/run/secrets/tailnet-authkey:ro",
            "",
            "networks:",
            "  tailnet-egress:",
            "    name: ${AFM_TEST_TAILNET_NETWORK:-afm-test-tailnet}",
            "    driver: bridge",
            "    ipam:",
            "      config:",
            "        - subnet: \"${AFM_TEST_TAILNET_SUBNET:-203.0.113.0/24}\"",
            "",
        ]
    )


def render_text(data: dict | None = None) -> str:
    spec = data or load_flavors()
    hub = spec["hub"]
    spokes = spec["spokes"]
    project = str(spec.get("project") or "afm-test")
    listen = str(spec.get("listen_all") or "unspecified")
    group = str(spec.get("seed_group") or "")
    names = " ".join(s["name"] for s in spokes)
    public_host = "${HUB_PUBLIC_HOST:-afm-test-hub}"
    lines: list[str] = [
        "# Generated from test-env/flavors.yml by test-env/scripts/render.py.",
        "# Do not edit by hand. Host publish is omitted on purpose.",
        f"name: {project}",
        "",
        "networks:",
        "  afm-test:",
        "    name: afm-test-net",
        "    driver: bridge",
        "    internal: true",
        "    # RFC 5737 documentation range. Placeholder only: override AFM_TEST_SUBNET.",
        "    # An explicit subnet skips the host address pool.",
        "    ipam:",
        "      config:",
        "        - subnet: \"${AFM_TEST_SUBNET:-192.0.2.0/24}\"",
        "",
        "volumes:",
        "  afm-test-hub:",
        "    name: afm-test-hub",
        "  afm-test-join-key:",
        "    name: afm-test-join-key",
    ]
    for spoke in spokes:
        name = spoke["name"]
        for vol in (
            f"afm-test-spoke-{name}",
            f"afm-test-home-{name}-mesh",
            f"afm-test-home-{name}-ansible",
            f"afm-test-join-{name}",
        ):
            lines.append(f"  {vol}:")
            lines.append(f"    name: {vol}")
    lines += [
        "",
        "x-logging: &logging",
        "  driver: json-file",
        "  options:",
        '    max-size: "10m"',
        '    max-file: "3"',
        "",
        "services:",
        "  hub:",
        "    build:",
        "      context: ..",
        "      dockerfile: lab/images/Dockerfile.hub",
        "      args:",
        f"        INSTALL_OPENCODE: \"{hub.get('install_opencode', '0')}\"",
        f"        INSTALL_WINDOWS: \"{hub.get('install_windows', '0')}\"",
        f"    hostname: {hub.get('hostname', 'afm-test-hub')}",
        f"    container_name: {hub.get('container_name', 'afm-test-hub')}",
        "    restart: unless-stopped",
        "    logging: *logging",
        *_harden("/home/mcp-join", "/home/labadmin"),
        "    networks: [afm-test]",
        f"    mem_limit: {_mem(hub['memory_mb'])}",
        f"    memswap_limit: {_mem(hub['memory_mb'])}",
        "    deploy:",
        "      resources:",
        "        limits:",
        f"          memory: {int(hub['memory_mb'])}M",
        "    volumes:",
        "      - afm-test-hub:/var/lib/ansible-flow/hub",
        "      - afm-test-join-key:/run/join-key",
    ]
    for spoke in spokes:
        lines.append(f"      - afm-test-join-{spoke['name']}:/run/join-drop/{spoke['name']}")
    lines += [
        "    environment:",
        "      ANSIBLE_FLOW_ROLE: hub",
        "      ANSIBLE_FLOW_HUB_DIR: /var/lib/ansible-flow/hub",
        "      ANSIBLE_FLOW_HUB_NAME: afm-test",
        "      ANSIBLE_FLOW_ENVIRONMENT: test",
        "      ANSIBLE_FLOW_SKIP_OPENCODE: \"1\"",
        "      ANSIBLE_FLOW_REQUIRE_CHECK: \"0\"",
        "      ANSIBLE_FLOW_SUPERVISE_HTTP: \"1\"",
        "      ANSIBLE_FLOW_MCP_HTTP: \"1\"",
        f"      ANSIBLE_FLOW_HTTP_HOST: \"{listen}\"",
        "      ANSIBLE_FLOW_HTTP_PORT: \"8790\"",
        "      ANSIBLE_FLOW_MCP_TOKEN_FILE: /var/lib/ansible-flow/hub/mcp.http.token",
        f"      ANSIBLE_FLOW_PUBLIC_HOST: \"{public_host}\"",
        "      ANSIBLE_FLOW_MCP_MAX_SESSIONS: \"32\"",
        "      ANSIBLE_FLOW_MCP_RATE_PER_MINUTE: \"120\"",
        "      ANSIBLE_FLOW_MCP_ALLOWED_HOSTS: \"afm-test-hub,hub\"",
        "      ANSIBLE_FLOW_ADMIN_BIND: localhost",
        "      ANSIBLE_FLOW_ADMIN_PORT: \"8789\"",
        f"      ANSIBLE_FLOW_TEST_SPOKES: \"{names}\"",
        f"      ANSIBLE_FLOW_TEST_GROUP: \"{group}\"",
        "      ANSIBLE_FLOW_JOIN_DROP: /run/join-drop",
        "      ANSIBLE_FLOW_JOIN_KEY_EXPORT: /run/join-key",
        "    healthcheck:",
        "      test: [\"CMD\", \"python3\", \"/usr/local/bin/hub-healthcheck.py\"]",
        "      interval: 15s",
        "      timeout: 5s",
        "      retries: 12",
        "      start_period: 40s",
    ]
    for spoke in spokes:
        name = spoke["name"]
        lines += [
            "",
            f"  {name}:",
            "    build:",
            "      context: ..",
            "      dockerfile: lab/images/Dockerfile.spoke",
            "      args:",
            f"        BASE_IMAGE: {spoke['base']}",
            f"        SPOKE_FAMILY: {spoke['family']}",
            f"    hostname: {name}",
            f"    container_name: afm-test-spoke-{name}",
            "    restart: unless-stopped",
            "    logging: *logging",
            *_harden(),
            "    networks: [afm-test]",
            f"    mem_limit: {_mem(spoke['memory_mb'])}",
            f"    memswap_limit: {_mem(spoke['memory_mb'])}",
            "    deploy:",
            "      resources:",
            "        limits:",
            f"          memory: {int(spoke['memory_mb'])}M",
            "    volumes:",
            f"      - afm-test-spoke-{name}:/var/lib/ansible-flow/spoke",
            f"      - afm-test-home-{name}-mesh:/home/mcp-spoke",
            f"      - afm-test-home-{name}-ansible:/home/mcp-ansible",
            "      - afm-test-join-key:/run/join-key:ro",
            f"      - afm-test-join-{name}:/run/join-drop:ro",
            "    environment:",
            "      ANSIBLE_FLOW_ROLE: spoke",
            "      ANSIBLE_FLOW_SPOKE_DIR: /var/lib/ansible-flow/spoke",
            "      ANSIBLE_FLOW_ENVIRONMENT: test",
            f"      SPOKE_NAME: {name}",
            "      ANSIBLE_FLOW_AUTOJOIN: \"1\"",
            "      ANSIBLE_FLOW_JOIN_DROP: /run/join-drop",
            "      ANSIBLE_FLOW_JOIN_KEY: /run/join-key/join_client",
            "      ANSIBLE_FLOW_JOIN_HUB: mcp-join@hub:22",
            f"      ANSIBLE_FLOW_PUBLIC_ADDR: {name}",
            "    depends_on:",
            "      hub:",
            "        condition: service_started",
            "    healthcheck:",
            "      test:",
            "        [\"CMD\", \"python3\", \"-c\", \"import socket; socket.create_connection(('localhost', 22), 3).close()\"]",
            "      interval: 15s",
            "      timeout: 5s",
            "      retries: 12",
            "      start_period: 25s",
        ]
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    text = render_text()
    COMPOSE.write_text(text, encoding="utf-8")
    TAILNET.write_text(render_tailnet(), encoding="utf-8")
    spec = load_flavors()
    print(f"wrote {COMPOSE} ({spec['_total_mb']} MiB limits / {spec['budget_mb']} budget)")


if __name__ == "__main__":
    main()
