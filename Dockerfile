# syntax=docker/dockerfile:1
# Official single-node hub. The multi-spoke lab stays in lab/images.
# Do not dockerignore catalog/schemas. Do not bake tokens or SSH keys.
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    ANSIBLE_FLOW_ROLE=hub \
    ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub \
    ANSIBLE_FLOW_HTTP_PORT=8789 \
    ANSIBLE_FLOW_PUBLIC_HOST=mcp.example.com \
    ANSIBLE_COLLECTIONS_PATH=/usr/share/ansible/collections \
    HOME=/var/lib/ansible-flow \
    ANSIBLE_LOCAL_TEMP=/tmp/ansible-flow \
    PATH="/usr/local/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl tini util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 ansible-flow \
    && useradd --system --uid 10001 --gid 10001 \
         --home-dir /var/lib/ansible-flow --shell /usr/sbin/nologin ansible-flow \
    && mkdir -p /var/lib/ansible-flow/hub /tmp/ansible-flow /usr/share/ansible/collections \
    && chown -R ansible-flow:ansible-flow /var/lib/ansible-flow /tmp/ansible-flow

WORKDIR /opt/ansible-flow-mcp
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY catalog ./catalog
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN python3 -m pip install --no-cache-dir --break-system-packages -e . \
    && ansible-galaxy collection install 'ansible.posix:1.6.2' -p /usr/share/ansible/collections \
    && chmod -R a+rX /usr/share/ansible/collections /opt/ansible-flow-mcp \
    && chmod 755 /usr/local/bin/entrypoint.sh

# hub init writes ed25519 keys on the volume. No sshd in this image.
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*

LABEL org.opencontainers.image.title="ansible-flow-mcp" \
      org.opencontainers.image.source="https://github.com/real-limitless/ansible-flow-mcp" \
      org.opencontainers.image.description="Ansible MCP hub with bearer-authenticated streamable HTTP" \
      org.opencontainers.image.version="0.1.3"

EXPOSE 8789
VOLUME ["/var/lib/ansible-flow/hub"]
HEALTHCHECK --interval=10s --timeout=3s --start-period=25s --retries=10 \
  CMD python3 -c "import os,urllib.request; p=os.environ.get('ANSIBLE_FLOW_HTTP_PORT','8789'); urllib.request.urlopen('http://127.0.0.1:%s/health'%p)"
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
