#!/bin/bash
# Scores every budget row in rivals-m: real output, then the generous constructions, then the paired comparison.
# Up to 6 scorers at a time, each with its own tokenizer server. rivals-m
B=/private/tmp/claude-501/-Users-ksirg-devel-cogito-mem/2f8e80c5-f08b-4456-93a3-d17ec6ff8ff3/scratchpad/rivals-m
R=/Users/ksirg/devel/cogito-mem/results/rivals-m/budget
W=/Users/ksirg/devel/cogito-mem/.claude/worktrees/agent-a1f6d0361068c1fe3
D=$B/data_m
PY=(bash "$B/adapters/budget_py.sh" budget_score.py)
mkdir -p "$R" "$R/log"
bash "$B/adapters/sync.sh"
"$B/shared/env/bin/python" -I "$B/adapters/budget_prepare.py" "$B/rows/budget"
throttle() { while [ "$(jobs -rp | wc -l)" -ge 6 ]; do sleep 2; done; }

"${PY[@]}" cogi --data-dir "$D" --rows "$B/rows/budget/cogi-data_m-all.jsonl" --out "$R/cogi.json" > "$R/log/cogi.log" 2>&1

for name in agentmemory-bm25 agentmemory-hybrid deja mempalace-mine hippo hippo-scripts_dense_only hippo-scripts_turn_sym hippo-scripts_turn_asym hippo-scripts_session_sym hippo-scripts_session_asym; do
  [ -f "$B/rows/budget/$name-data_m-all.jsonl" ] || { echo "no rows for $name"; continue; }
  throttle
  "${PY[@]}" shipped --data-dir "$D" --rows "$B/rows/budget/$name-data_m-all.jsonl" --name "$name" --out "$R/shipped_$name.json" > "$R/log/shipped_$name.log" 2>&1 &
done
for name in mempalace-raw mempalace-hybrid_v4; do
  throttle
  "${PY[@]}" documents --data-dir "$D" --rank "$B/rows/$name-data_m-all.jsonl" --name "$name" --out "$R/shipped_$name.json" > "$R/log/shipped_$name.log" 2>&1 &
done
wait

COGI_RANK=/Users/ksirg/devel/cogito-mem/results/long-history/m-recall-b904848.json
for name in cogi-ranking agentmemory-bm25 agentmemory-hybrid deja-default mempalace-raw mempalace-hybrid_v4 hippo-lifted hippo-best_turn_sym hippo-best_session_sym; do
  rank=$B/rows/$name-data_m-all.jsonl
  [ "$name" = cogi-ranking ] && rank=$COGI_RANK
  for spec in "message 10" "piece 10" "message 5" "message 20"; do
    set -- $spec
    throttle
    "${PY[@]}" generous --data-dir "$D" --rank "$rank" --name "$name" --unit "$1" --k "$2" --out "$R/generous_$1$2_$name.json" > "$R/log/generous_$1$2_$name.log" 2>&1 &
  done
done
wait
cat "$R"/log/*.log | grep -E 'Traceback|Error' | sort | uniq -c | head
ls "$R" | wc -l
"${PY[@]}" compare --cogi "$R/cogi.json" --cogi-src "$W/src" --out "$R/comparison.json" "$R"/shipped_*.json "$R"/generous_*.json
