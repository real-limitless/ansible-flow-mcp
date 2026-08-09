#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p keys
# placeholder so compose bind-mount exists
touch keys/.gitkeep

if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  COMPOSE=(podman compose)
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Need docker compose or podman compose" >&2
  exit 1
fi

echo "Using: ${COMPOSE[*]}"
"${COMPOSE[@]}" -f docker-compose.yml up -d --build "$@"
echo "Waiting for health..."
sleep 3
"${COMPOSE[@]}" -f docker-compose.yml ps
