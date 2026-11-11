#!/usr/bin/env bash
# Run the engine comparison one step at a time, so no two timed steps share the CPU.
#   scripts/engines/run_all.sh <python with sqlite-vec, zvec, lancedb, psutil> <longmemeval_s_cleaned.json> <out folder>
set -euo pipefail
PY=$1
DATA=$2
OUT=$3
B="$(cd "$(dirname "$0")" && pwd)/bench.py"
mkdir -p "$OUT"
R="$OUT/m10"
[ -f "$R/fill.json" ] || "$PY" "$B" fill --data "$DATA" --root "$R" --tokens 10M
[ -f "$R/queries.json" ] || "$PY" "$B" queries --data "$DATA" --root "$R"
for e in sqlite zvec lance; do
  [ -f "$R/build-$e.json" ] || "$PY" "$B" build --root "$R" --engine "$e" > "$R/build-$e.log" 2>&1
done
for e in baseline sqlite zvec lance; do
  "$PY" "$B" speed --root "$R" --engine "$e" > "$R/speed-$e.log" 2>&1
done
"$PY" "$B" parity --root "$R" > "$R/parity.log" 2>&1
"$PY" "$B" scale --root "$OUT/scale" --items 1000000 --queries 500 --out "$OUT/scale.json" > "$OUT/scale.log" 2>&1
echo done
