# Shared compose helpers for the private test lab. Source, do not execute.
set -euo pipefail

TEST_ENV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AFM_PROJECT="${AFM_PROJECT:-afm-test}"

compose() {
  local files=(-f "$TEST_ENV_ROOT/docker-compose.yml")
  if [ "${AFM_TEST_ATTACH_PRIVATE_NET:-0}" = "1" ]; then
    files+=(-f "$TEST_ENV_ROOT/docker-compose.private-net.yml")
  fi
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose --project-name "$AFM_PROJECT" "${files[@]}" "$@"
  elif command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
    podman compose --project-name "$AFM_PROJECT" "${files[@]}" "$@"
  else
    echo "docker compose or podman compose is required" >&2
    return 127
  fi
}

runtime_bin() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo docker
    return 0
  fi
  if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
    echo podman
    return 0
  fi
  return 127
}
