#!/bin/bash
# One token-budget job, resumable. Rivals run in the sandbox; Cogi runs from its frozen source with its own environment.
#
#   RIVALS_BASE=<rivals-m> budget_one.sh budget-<system> <data_m> <all|sample100|pilot20>
#
# Writes rivals-m/rows/budget/<system>-<data>-<sample>.jsonl
set -euo pipefail
export RIVALS_BASE=${RIVALS_BASE:?}
setting=$1 data=$2 sample=$3
system=${setting#budget-}
B=$RIVALS_BASE
dir=$B/$data
A=$B/adapters
out=$B/rows/budget/$system-$data-$sample.jsonl
mkdir -p "$B/rows/budget"
sb=(caffeinate -is nice -n 10 bash "$A/run_sandboxed.sh")
head() { printf '{"settings":{"system":"%s","project":"%s","commit":"%s","returns":"%s","sample":"%s"}}' "$system" "$1" "$2" "$3" "$sample"; }

case $system in
  cogi)
    mkdir -p "$B/cogi"
    [ -f "$B/cogi/embeddings.sqlite3" ] || cp /Users/ksirg/devel/cogito-mem/data/longmemeval_m/embeddings.sqlite3 "$B/cogi/embeddings.sqlite3"
    exec env -i PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin" HOME="$HOME" TMPDIR="$B/cogi" LANG=en_US.UTF-8 COGITO_MEM_NO_DOWNLOAD=1 \
      PYTHONPATH=/Users/ksirg/devel/cogito-mem/data/frozen/src-b904848/src \
      caffeinate -is nice -n 10 /Users/ksirg/devel/cogito-mem/.venv/bin/python "$A/budget_cogi.py" --data-dir "$dir" --cache "$B/cogi/embeddings.sqlite3" --sample "$sample" --out "$out"
    ;;
  agentmemory-bm25|agentmemory-hybrid)
    export RIVALS_PATH=/usr/local/bin:/usr/bin:/bin
    H=$(head agentmemory c6c476d2905926727fa5848a134d7a3b38a7fa98 "buildRecallResponse, format full, limit 20, token_budget N: whole sessions, first clipped")
    "${sb[@]}" agentmemory node --import tsx benchmark/rivals_budget.ts --data-dir "$dir" --sample "$sample" --adapter "${system#agentmemory-}" --out "$out" --header "$H"
    ;;
  deja)
    H=$(head deja-vu 064f9ba0c7109a2dd6a149b9d92c00b03d3970a1 "deja recall pages: snippets per session, 5 hits, 4 KB a page, --offset for more")
    "${sb[@]}" dejavu "$B/shared/env/bin/python" "$A/budget_deja.py" --deja "$B/dejavu/deja" --data-dir "$dir" --work "$B/dejavu/tmp/budget" --sample "$sample" --out "$out" --header "$H"
    ;;
  mempalace-mine)
    H=$(head mempalace 4f7745afbd9d0197c6475b4c7ac846d4932eaeda "mine --mode convos + search: drawers of up to 800 characters; no budget option; 50 asked for")
    # About 56 s a question, so 6 processes; each writes its own rows file, merged when scored.
    n=${MEMPALACE_SHARDS:-6}
    for ((i = 0; i < n; i++)); do
      "${sb[@]}" mempalace "$B/mempalace/env/bin/python" "$A/budget_mempalace.py" --data-dir "$dir" --work "$B/mempalace/tmp/budget" --sample "$sample" --shard "$i/$n" --out "$out.shard$i" --header "$H" &
    done
    status=0
    for job in $(jobs -p); do wait "$job" || status=1; done
    exit $status
    ;;
  hippo)
    export RIVALS_PATH=/usr/local/bin:/usr/bin:/bin
    H=$(head hippo-memory cc59e7bd34a8c52cb6107665fc33824a6c832b14 "hippo recall --budget N: whole sessions, first kept even over budget")
    "${sb[@]}" hippo "$B/shared/env/bin/python" "$A/budget_hippo.py" --hippo "$B/hippo/repo/bin/hippo.js" --data-dir "$dir" --work "$B/hippo/work/budget-$data-$sample" --sample "$sample" --workers 8 --out "$out" --header "$H"
    ;;
  hippo-scripts)
    export RIVALS_PATH=/usr/local/bin:/usr/bin:/bin
    H=$(head hippo-memory cc59e7bd34a8c52cb6107665fc33824a6c832b14 "benchmark scripts: each ranked session's best dense turn")
    RIVALS_ENV="HIPPO_MODEL_CACHE=$B/hippo/models" "${sb[@]}" hippo node --max-old-space-size=32000 benchmarks/longmemeval/rivals_best.mjs --data-dir "$dir" --work "$B/hippo/best/$data" --out-prefix "$B/rows/hippo-best" --suffix "$data-$sample" --header-json "$H" --turn-out "$out"
    ;;
  *)
    echo "unknown system $system" >&2
    exit 2
    ;;
esac
