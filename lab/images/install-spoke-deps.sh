#!/bin/sh
set -eu
family="${1:-debian}"

install_debian() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    openssh-server openssh-client \
    iproute2 ca-certificates tini sudo
  rm -rf /var/lib/apt/lists/*
  # nologin path
  if [ ! -e /usr/sbin/nologin ] && [ -e /sbin/nologin ]; then
    ln -sf /sbin/nologin /usr/sbin/nologin || true
  fi
}

pkg_rhel() {
  if command -v microdnf >/dev/null 2>&1; then
    microdnf install -y "$@"
    microdnf clean all
  else
    dnf install -y --setopt=install_weak_deps=False "$@"
    dnf clean all
  fi
}

link_newer_python() {
  # Rocky 9's default python3 is 3.9. This package needs >= 3.11.
  if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    return 0
  fi
  py=""
  for candidate in python3.13 python3.12 python3.11; do
    if pkg_rhel "$candidate" "${candidate}-pip"; then
      py="$candidate"
      break
    fi
  done
  if [ -z "$py" ]; then
    echo "no Python >= 3.11 package on this image" >&2
    return 1
  fi
  bin="$(command -v "$py")"
  ln -sfn "$bin" /usr/local/bin/python3
  if [ -x "${bin%/*}/pip${bin#*python}" ]; then
    ln -sfn "${bin%/*}/pip${bin#*python}" /usr/local/bin/pip3
  elif "$bin" -m pip --version >/dev/null 2>&1; then
    ln -sfn "$bin" /usr/local/bin/python3
  fi
  /usr/local/bin/python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
}

install_rhel() {
  pkg_rhel python3 python3-pip openssh-server openssh-clients iproute ca-certificates which shadow-utils tar gzip sudo
  link_newer_python
  # tini optional
  if ! command -v tini >/dev/null 2>&1; then
    printf '%s\n' '#!/bin/sh' 'exec "$@"' >/usr/local/bin/tini
    chmod +x /usr/local/bin/tini
  fi
}

install_alpine() {
  apk add --no-cache \
    python3 py3-pip \
    openssh openssh-server openssh-client \
    iproute2 ca-certificates tini shadow sudo bash
  # alpine uses /sbin/nologin
  mkdir -p /usr/sbin
  ln -sf /sbin/nologin /usr/sbin/nologin || true
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "alpine python3 is older than 3.11" >&2
    exit 1
  fi
}

case "$family" in
  debian|ubuntu) install_debian ;;
  rocky|fedora|rhel) install_rhel ;;
  alpine) install_alpine ;;
  *) echo "unknown SPOKE_FAMILY=$family" >&2; exit 1 ;;
esac

mkdir -p /var/run/sshd /etc/ssh/sshd_config.d
# Some bases (Alpine) do not Include the drop-in directory unless asked.
if [ -f /etc/ssh/sshd_config ] && ! grep -qE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config.d/' /etc/ssh/sshd_config; then
  printf '\nInclude /etc/ssh/sshd_config.d/*.conf\n' >> /etc/ssh/sshd_config
fi
