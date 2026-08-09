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

install_rhel() {
  if command -v microdnf >/dev/null 2>&1; then
    microdnf install -y python3 python3-pip openssh-server openssh-clients iproute ca-certificates which shadow-utils tar gzip
    microdnf clean all
  else
    dnf install -y python3 python3-pip openssh-server openssh-clients iproute ca-certificates which shadow-utils tar gzip
    dnf clean all
  fi
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
    iproute2 ca-certificates tini shadow
  # alpine uses /sbin/nologin
  mkdir -p /usr/sbin
  ln -sf /sbin/nologin /usr/sbin/nologin || true
}

case "$family" in
  debian|ubuntu) install_debian ;;
  rocky|fedora|rhel) install_rhel ;;
  alpine) install_alpine ;;
  *) echo "unknown SPOKE_FAMILY=$family" >&2; exit 1 ;;
esac

mkdir -p /var/run/sshd /etc/ssh/sshd_config.d
