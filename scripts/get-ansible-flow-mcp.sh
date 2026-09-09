#!/usr/bin/env bash
# Clone DEVELOPMENT and start Compose. Family ritual from TheFLOW.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/real-limitless/ansible-flow-mcp.git}"
BRANCH="${BRANCH:-DEVELOPMENT}"
CLONE_DIR="${CLONE_DIR:-$HOME/src/ansible-flow-mcp}"
PORT="${ANSIBLE_FLOW_HTTP_PORT:-8789}"

fail() { echo "$*" >&2; exit 1; }

compose_cmd() {
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  elif command -v podman >/dev/null && podman compose version >/dev/null 2>&1; then
    echo "podman compose"
  else
    return 1
  fi
}

command -v git >/dev/null || fail "git is required"
compose_cmd >/dev/null || fail "Docker Compose or Podman Compose is required"

if [ ! -d "$CLONE_DIR/.git" ]; then
  mkdir -p "$(dirname "$CLONE_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$CLONE_DIR"
fi

cd "$CLONE_DIR"
if [ -f .env.example ] && [ ! -f .env ]; then
  cp .env.example .env
fi

dc="$(compose_cmd)"
# shellcheck disable=SC2086
$dc up -d --build
echo "Up. Host port ${PORT}."
if [ -x scripts/doctor.sh ]; then
  scripts/doctor.sh || true
fi
