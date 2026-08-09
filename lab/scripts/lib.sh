# shellcheck shell=bash
# Shared helpers for lab scripts. Source from scripts:  # shellcheck source=lib.sh
#   ROOT=...; source "$ROOT/scripts/lib.sh"

lab_compose_cmd() {
  if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
    COMPOSE=(podman compose)
  elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    echo "Need docker compose or podman compose" >&2
    return 1
  fi
}

lab_compose_files_base() {
  COMPOSE_FILES=(-f docker-compose.yml)
}

lab_compose_files_windows() {
  COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.windows.yml)
}

lab_compose() {
  "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" "$@"
}

lab_run_hub() {
  lab_compose exec -T hub "$@"
}

lab_require_kvm() {
  if [ ! -e /dev/kvm ]; then
    cat >&2 <<'EOF'
ERROR: /dev/kvm not found. Windows lab needs KVM on a Linux host.

  sudo kvm-ok    # or: ls -l /dev/kvm
  # Enable VT-x/AMD-V in firmware; nested virt if the host is a VM.

Docker Desktop on macOS/Windows is not supported for dockur/windows.
EOF
    return 1
  fi
  if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
    echo "ERROR: /dev/kvm exists but is not read/write for this user (try group kvm)." >&2
    return 1
  fi
}

lab_load_windows_env() {
  # Optional overrides from lab/windows/.env
  local envf="${ROOT}/windows/.env"
  if [ -f "$envf" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$envf"
    set +a
  fi
  export WIN_USERNAME="${WIN_USERNAME:-Docker}"
  export WIN_PASSWORD="${WIN_PASSWORD:-admin}"
  export WIN_RAM_SIZE="${WIN_RAM_SIZE:-4G}"
  export WIN_CPU_CORES="${WIN_CPU_CORES:-2}"
  export WIN_DISK_SIZE="${WIN_DISK_SIZE:-64G}"
  export WIN_CLIENT_VERSION="${WIN_CLIENT_VERSION:-11}"
  export WIN_SERVER_VERSION="${WIN_SERVER_VERSION:-2022}"
}
