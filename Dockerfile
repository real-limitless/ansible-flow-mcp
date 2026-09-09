# syntax=docker/dockerfile:1
# Single-node hub + HTTP health. Multi-spoke fabric stays in lab/.
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    ANSIBLE_FLOW_ROLE=hub \
    ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub \
    ANSIBLE_FLOW_HTTP_PORT=8789 \
    PATH="/usr/local/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/ansible-flow/hub

WORKDIR /opt/ansible-flow-mcp
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY catalog ./catalog
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN python3 -m pip install --no-cache-dir --break-system-packages -e . \
    && chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8789
VOLUME ["/var/lib/ansible-flow/hub"]
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=10 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8789/health')"
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
