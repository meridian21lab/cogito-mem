#!/bin/bash
# Waits until no other eval or test is running on this Mac.
# Exit 0: the check came back empty twice in a row, 10 minutes apart.
# Exit 3: still busy after the 24-hour limit; stop and report, do not start.
# Each check is appended to the log so waiting time and overlaps can be reported.
# The 24-hour clock counts from the first wait, 2026-11-01T21:04:20Z, unless WAIT_START (epoch seconds) says otherwise.
LOG="$(dirname "$0")/wait_quiet.log"
PATTERN='cogito-mem eval|cogito-mem bench|long-history|longmemeval|score_design|serve --port 74|pytest|judge5/|live5/'
INTERVAL=600
LIMIT=$((24 * 3600))
start=${WAIT_START:-$(date -j -u -f %FT%TZ 2026-11-01T21:04:20Z +%s)}
empty=0
echo "=== wait (re)started $(date -u +%FT%TZ), pattern: $PATTERN" >> "$LOG"
while :; do
  # Only process header lines: a matched shell's multi-line command would otherwise fill the log.
  found=$(pgrep -fl "$PATTERN" | grep -E '^[0-9]+ ' | grep -v "^$$ " | cut -c1-200)
  now=$(date -u +%FT%TZ)
  if [ -z "$found" ]; then
    empty=$((empty + 1))
    echo "$now empty ($empty of 2)" >> "$LOG"
  else
    empty=0
    echo "$now busy:" >> "$LOG"
    echo "$found" >> "$LOG"
  fi
  waited=$(( $(date +%s) - start ))
  if [ "$empty" -ge 2 ]; then
    echo "QUIET after ${waited}s at $now" | tee -a "$LOG"
    exit 0
  fi
  if [ "$waited" -ge "$LIMIT" ]; then
    echo "STILL BUSY after ${waited}s at $now" | tee -a "$LOG"
    exit 3
  fi
  sleep "$INTERVAL"
done
