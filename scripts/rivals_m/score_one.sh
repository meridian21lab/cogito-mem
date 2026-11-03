#!/bin/bash
# score_one.sh <name> <data> <sample> <outdir> [expect]. name is the rows prefix, e.g. hippo-default.
B=/private/tmp/claude-501/-Users-ksirg-devel-cogito-mem/2f8e80c5-f08b-4456-93a3-d17ec6ff8ff3/scratchpad/rivals-m
W=/Users/ksirg/devel/cogito-mem/.claude/worktrees/agent-a1f6d0361068c1fe3
name=$1 data=$2 sample=$3 out=$4 expect=${5:-}
job=$name
case $name in hippo-best*) job=hippo-best ;; hippo-*) job=hippo ;; esac
meta="{}"
[ -f "$B/rows/$job-$data-$sample.wall.json" ] && meta=$("$B/shared/env/bin/python" -I -c "import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps({'wall_s': d['running_s'], 'run': d}))" "$B/rows/$job-$data-$sample.wall.json")
exec "$B/shared/env/bin/python" -I "$B/adapters/score_rows.py" --cogi-src "$W/src" --data-dir "$B/$data" --rows "$B/rows/$name-$data-$sample.jsonl" --out "$out/$name-$data-$sample.json" --meta "$meta" ${expect:+--expect "$expect"}
