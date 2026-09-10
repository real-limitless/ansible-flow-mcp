#!/usr/bin/env bash
# Idempotent repo bootstrap for the ProjectEverflow CORE checkout.
#
# CORE ships concept + methodology docs plus the graphify skill that AGENTS.md
# tells agents to use for codebase questions. Install the graphify CLI
# (`graphifyy`) so `graphify query|path|explain|update` work out of the box, and
# make its user-script dir resolvable in interactive shells.
set -euo pipefail

python3 -m pip install --user --upgrade graphifyy

# Ensure pip's --user script dir is on PATH for future shells (idempotent).
BASHRC="${HOME}/.bashrc"
LINE='export PATH="$HOME/.local/bin:$PATH"'
touch "${BASHRC}"
grep -qxF "${LINE}" "${BASHRC}" || printf '%s\n' "${LINE}" >> "${BASHRC}"

# Prove the tool resolves in this run's logs.
export PATH="${HOME}/.local/bin:${PATH}"
if graphify --help >/dev/null 2>&1; then
  echo "install: graphify CLI ready ($(command -v graphify))"
else
  echo "install: graphify importable via python3 -m graphify"
fi
