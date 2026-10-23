#!/usr/bin/env bash
# Record docker/podman stats. Prints only what the runtime reports.
# Usage: measure.sh idle | measure.sh smoke
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"

phase="${1:-idle}"
if ! bin="$(runtime_bin)"; then
  echo "MEASUREMENT PENDING: docker and podman are not available in this environment." >&2
  echo "Re-run test-env/scripts/measure.sh idle and measure.sh smoke where a runtime is installed." >&2
  exit 2
fi

stats_once() {
  if [ "$bin" = "docker" ]; then
    docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}'
  else
    podman stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}'
  fi
}

filter_lab() {
  # Container names from this project only.
  grep -E '^(afm-test-hub|afm-test-spoke-)' || true
}

echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) phase=${phase} runtime=${bin}"

if [ "$phase" = "idle" ]; then
  echo "BEGIN STATS"
  stats_once | filter_lab
  echo "END STATS"
  exit 0
fi

if [ "$phase" != "smoke" ]; then
  echo "usage: $0 idle|smoke" >&2
  exit 2
fi

tmp="$(mktemp)"
(
  while true; do
    stats_once | filter_lab >>"$tmp" || true
    sleep 2
  done
) &
sampler=$!
set +e
"$ROOT/scripts/smoke.sh"
smoke_rc=$?
set -e
kill "$sampler" 2>/dev/null || true
wait "$sampler" 2>/dev/null || true
echo "BEGIN SAMPLES"
cat "$tmp"
echo "END SAMPLES"
python3 - "$tmp" <<'PY'
import re, sys
path = sys.argv[1]
mult = {"b": 1, "kib": 1024, "kb": 1000, "mib": 1024**2, "mb": 1000**2, "gib": 1024**3, "gb": 1000**3}
peak = {}
def parse(text):
    m = re.match(r"([0-9.]+)\s*([A-Za-z]+)", text.strip())
    if not m:
        return None
    return float(m.group(1)) * mult.get(m.group(2).lower(), 1)
for line in open(path, encoding="utf-8"):
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 2:
        continue
    name, usage = parts[0], parts[1].split("/")[0]
    val = parse(usage)
    if val is None:
        continue
    peak[name] = max(peak.get(name, 0), val)
def fmt(n):
    return f"{n/1024/1024:.1f} MiB"
print("PEAK FROM SAMPLES")
total = 0.0
for name in sorted(peak):
    total += peak[name]
    print(f"{name}\t{fmt(peak[name])}")
print(f"total_peak\t{fmt(total)}")
PY
rm -f "$tmp"
exit "$smoke_rc"
