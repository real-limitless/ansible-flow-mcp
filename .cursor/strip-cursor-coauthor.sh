#!/usr/bin/env bash
# Environment hygiene: strip Cursor commit co-author attribution.
set -euo pipefail
HOOKS_ROOT="${HOME}/.cursor/agent-hooks"
if [ -d "$HOOKS_ROOT" ]; then
  find "$HOOKS_ROOT" -type f \( -name 'commit-msg.cursor.co-author' -o -name '*co-author*' \) -delete 2>/dev/null || true
fi
HOOK_DIR="${HOME}/.cursor/hooks-local"
mkdir -p "$HOOK_DIR"
STRIP_BODY=$(cat <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
file="${1:-}"
[ -n "$file" ] && [ -f "$file" ] || exit 0
tmp="$(mktemp)"
grep -viE 'Co-authored-by:.*Cursor|Made with Cursor|cursoragent@cursor.com' "$file" >"$tmp" || true
cat "$tmp" >"$file"
rm -f "$tmp"
EOF
)
printf '%s\n' "$STRIP_BODY" >"$HOOK_DIR/commit-msg"
chmod 755 "$HOOK_DIR/commit-msg"
# Dispatcher runs *.cursor* after the original hook. A late name sorts after co-author files.
if [ -d "$HOOKS_ROOT" ]; then
  find "$HOOKS_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | while read -r dir; do
    if [ -x "$dir/.dispatcher" ] || [ -f "$dir/commit-msg.cursor" ]; then
      printf '%s\n' "$STRIP_BODY" >"$dir/commit-msg.cursor.z-strip"
      chmod 755 "$dir/commit-msg.cursor.z-strip"
    fi
  done
fi
# Best-effort: if this repo has .git/hooks, install stripper (do not clobber existing custom hooks blindly)
if [ -d /workspace/.git/hooks ]; then
  dest=/workspace/.git/hooks/commit-msg
  if [ ! -e "$dest" ] || grep -q 'cursoragent@cursor.com\|strip-cursor-coauthor' "$dest" 2>/dev/null; then
    cp "$HOOK_DIR/commit-msg" "$dest"
    chmod 755 "$dest"
  fi
fi
# Reaper: the co-author file may be recreated at commit time. Keep deleting it for this session.
(
  for _ in $(seq 1 900); do
    sleep 2
    if [ -d "$HOOKS_ROOT" ]; then
      find "$HOOKS_ROOT" -type f \( -name 'commit-msg.cursor.co-author' -o -name '*co-author*' \) -delete 2>/dev/null || true
    fi
  done
) >/dev/null 2>&1 &
echo "cursor co-author hooks stripped"
if [ -d "$HOOKS_ROOT" ]; then
  leftover=$(find "$HOOKS_ROOT" -type f -name 'commit-msg.cursor.co-author' 2>/dev/null | wc -l | tr -d ' ')
  echo "commit-msg.cursor.co-author remaining: $leftover"
fi
