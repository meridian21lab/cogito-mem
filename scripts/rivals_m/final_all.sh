#!/bin/bash
# Final scoring of every long-history setting; writes results/rivals-m/comparison.json and the tables to tables.md.
B=/private/tmp/claude-501/-Users-ksirg-devel-cogito-mem/2f8e80c5-f08b-4456-93a3-d17ec6ff8ff3/scratchpad/rivals-m
W=/Users/ksirg/devel/cogito-mem/.claude/worktrees/agent-a1f6d0361068c1fe3
R=/Users/ksirg/devel/cogito-mem/results/rivals-m
bash "$B/adapters/sync.sh"
bash "$B/adapters/score_best.sh" data_m "$R"
files=()
for name in agentmemory-bm25 agentmemory-hybrid deja-default mempalace-raw mempalace-hybrid_v4 hippo-default hippo-lifted hippo-best_dense_only hippo-best_turn_sym hippo-best_turn_asym hippo-best_session_sym hippo-best_session_asym; do
  bash "$B/adapters/score_one.sh" "$name" data_m all "$R" 500 > /dev/null
  files+=("$R/$name-data_m-all.json")
done
"$B/shared/env/bin/python" -I "$B/adapters/analyze.py" --cogi-src "$W/src" --cogi /Users/ksirg/devel/cogito-mem/results/long-history/m-recall-b904848.json --out "$R/comparison.json" "${files[@]}" | sed 's/-data_m-all//' > "$R/tables.md"
grep -E 'hippo-best' "$R/tables.md" | cut -c1-170
echo; grep -c NO "$R/tables.md"
grep -E 'embedding finished|distinct turns|corpora|done:' "$B/rows/hippo-best-data_m-all.log" | cut -c1-160
"$B/shared/env/bin/python" -I "$B/adapters/validate.py" "$R" "$B" /Users/ksirg/devel/cogito-mem/results/long-history/m-recall-b904848.json | grep -A1 hippo-best | cut -c1-220
du -sh "$B/hippo/best/data_m" | cut -f1
ls "$R" | head -40
