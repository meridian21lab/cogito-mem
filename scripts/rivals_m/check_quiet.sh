#!/bin/bash
# One-shot check before each stage. Prints other jobs that count as busy; exit 1 if any.
# Anything mentioning rivals-m is one of this run's own jobs, and is ignored.
PATTERN='cogito-mem eval|cogito-mem bench|long-history|longmemeval|score_design|serve --port 74|pytest|judge5/|live5/'
found=$(pgrep -fl "$PATTERN" | grep -E '^[0-9]+ ' | grep -v "^$$ " | grep -v 'rivals-m' | cut -c1-160)
echo "$(date -u +%FT%TZ) check" >> "$(dirname "$0")/wait_quiet.log"
if [ -n "$found" ]; then
  echo "BUSY:"; echo "$found"; echo "$found" >> "$(dirname "$0")/wait_quiet.log"
  exit 1
fi
echo QUIET
