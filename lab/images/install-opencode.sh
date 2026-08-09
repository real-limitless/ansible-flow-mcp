#!/bin/bash
# Best-effort OpenCode install for lab hub image.
set -euo pipefail

if command -v opencode >/dev/null 2>&1; then
  echo "opencode already present: $(command -v opencode)"
  exit 0
fi

# 1) Official installer (preferred)
if curl -fsSL https://opencode.ai/install 2>/dev/null | bash; then
  if [ -x "${HOME}/.opencode/bin/opencode" ]; then
    ln -sfn "${HOME}/.opencode/bin/opencode" /usr/local/bin/opencode
  fi
fi

if command -v opencode >/dev/null 2>&1; then
  opencode --version 2>/dev/null || opencode --help >/dev/null
  echo "opencode installed via official installer"
  exit 0
fi

# 2) Node + npm global (fallback package names)
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y --no-install-recommends nodejs
fi

for pkg in opencode-ai @sst/opencode opencode; do
  if npm install -g "$pkg" 2>/dev/null; then
    break
  fi
done

# link common locations
for c in \
  /usr/bin/opencode \
  /usr/local/bin/opencode \
  /usr/lib/node_modules/opencode-ai/bin/opencode \
  /usr/lib/node_modules/opencode/bin/opencode \
  "$(npm root -g 2>/dev/null)/opencode-ai/bin/opencode" \
  "$(npm root -g 2>/dev/null)/@sst/opencode/bin/opencode"
do
  if [ -n "$c" ] && [ -x "$c" ]; then
    ln -sfn "$c" /usr/local/bin/opencode
    break
  fi
done

if command -v opencode >/dev/null 2>&1; then
  echo "opencode installed via npm"
  exit 0
fi

echo "WARNING: opencode not installed — lab AI scripts will fail until fixed" >&2
exit 0
