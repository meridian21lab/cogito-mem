#!/bin/bash
# score_best.sh <data> <outdir> : scores hippo's five benchmark settings.
B=/private/tmp/claude-501/-Users-ksirg-devel-cogito-mem/2f8e80c5-f08b-4456-93a3-d17ec6ff8ff3/scratchpad/rivals-m
tail -4 "$B/rows/hippo-best-$1-all.log" | cut -c1-160
for s in dense_only turn_sym turn_asym session_sym session_asym; do
  echo "--- $s"
  bash "$B/adapters/score_one.sh" "hippo-best_$s" "$1" all "$2" 500 | grep -E '^all questions|^answerable|load median .* p95'
done
