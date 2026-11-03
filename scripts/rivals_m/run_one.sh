#!/bin/bash
# One setting of one rival on one split and sample, resumable, in the sandbox.
#
#   RIVALS_BASE=<rivals-m> run_one.sh <setting> <data_m|data_s> <all|sample100|pilot20>
#
# Writes rivals-m/rows/<setting>-<data>-<sample>.jsonl (hippo writes a pair, default and lifted, from one build).
set -euo pipefail
export RIVALS_BASE=${RIVALS_BASE:?}
setting=$1 data=$2 sample=$3
B=$RIVALS_BASE
dir=$B/$data
tag=$data-$sample
A=$B/adapters
sb=(caffeinate -is nice -n 10 bash "$A/run_sandboxed.sh")
head() { printf '{"settings":{"setting":"%s","project":"%s","commit":"%s","version":"%s","indexes":"%s","embedder":"%s","llm":"none","sample":"%s","flags":"%s"}}' "$setting" "$1" "$2" "$3" "$4" "$5" "$sample" "$6"; }

case $setting in
  agentmemory-bm25|agentmemory-hybrid)
    C=c6c476d2905926727fa5848a134d7a3b38a7fa98
    export RIVALS_PATH=/usr/local/bin:/usr/bin:/bin
    if [ "$setting" = agentmemory-bm25 ]; then
      H=$(head agentmemory "$C" 0.9.31 "whole sessions, both roles, role-flattened; repeated ids coalesced" "none (BM25 only; no key or EMBEDDING_PROVIDER set)" "adapter=bm25 k=100"); ad=bm25
    else
      H=$(head agentmemory "$C" 0.9.31 "whole sessions, both roles; vectors from the first 512 characters" "local all-MiniLM-L6-v2 (older benchmark script)" "adapter=hybrid k=100 weights=0.4:0.6"); ad=hybrid
    fi
    "${sb[@]}" agentmemory node --import tsx benchmark/rivals_m.ts --data-dir "$dir" --sample "$sample" --adapter "$ad" --out "$B/rows/$setting-$tag.jsonl" --header "$H"
    ;;
  deja-default)
    C=064f9ba0c7109a2dd6a149b9d92c00b03d3970a1
    H=$(head deja-vu "$C" "$C" "one transcript per session, both roles, messages indexed" "none (lexical ladder)" "search.Options{All:true}, Now=question date")
    RIVALS_ENV="DEJA_EMBED_OFF=1" "${sb[@]}" dejavu "$B/dejavu/rivalsm" -data-dir "$dir" -sample "$sample" -out "$B/rows/$setting-$tag.jsonl" -header "$H"
    ;;
  mempalace-raw|mempalace-hybrid_v4)
    C=4f7745afbd9d0197c6475b4c7ac846d4932eaeda
    mode=${setting#mempalace-}
    H=$(head mempalace "$C" 3.12.0 "whole sessions, user turns only, joined; embedder reads the first 256 tokens" "chroma default all-MiniLM-L6-v2 ONNX" "mode=$mode granularity=session n_results=100")
    "${sb[@]}" mempalace "$B/mempalace/env/bin/python" "$A/mempalace_run.py" --repo "$B/mempalace/repo" --data-dir "$dir" --sample "$sample" --mode "$mode" --out "$B/rows/$setting-$tag.jsonl" --header "$H"
    ;;
  hippo)
    C=cc59e7bd34a8c52cb6107665fc33824a6c832b14
    export RIVALS_PATH=/usr/local/bin:/usr/bin:/bin
    H=$(head hippo-memory "$C" 3.1.0 "whole sessions, both roles, turn contents joined" "none (default install, BM25)" "hippo remember per session; recall at default and lifted budget; workers=${HIPPO_WORKERS:-8}")
    "${sb[@]}" hippo "$B/shared/env/bin/python" "$A/hippo_run.py" --hippo "$B/hippo/repo/bin/hippo.js" --data-dir "$dir" --work "$B/hippo/work/$tag" --sample "$sample" --workers "${HIPPO_WORKERS:-8}" --out-default "$B/rows/hippo-default-$tag.jsonl" --out-lifted "$B/rows/hippo-lifted-$tag.jsonl" --header "$H"
    ;;
  hippo-best)
    # The benchmark scripts behind hippo's published 98.0, five settings at once. Whole split only: BM25 statistics are file-wide.
    C=cc59e7bd34a8c52cb6107665fc33824a6c832b14
    export RIVALS_PATH=/usr/local/bin:/usr/bin:/bin
    H=$(head hippo-memory "$C" 3.1.0 "every distinct turn embedded, both roles; BM25 on turns or joined sessions; statistics over the whole file" "Xenova/all-MiniLM-L6-v2 fp32, @huggingface/transformers 4.2.0" "benchmark scripts, not hippo recall")
    RIVALS_ENV="HIPPO_MODEL_CACHE=$B/hippo/models" "${sb[@]}" hippo node --max-old-space-size=32000 benchmarks/longmemeval/rivals_best.mjs --data-dir "$dir" --work "$B/hippo/best/$data" --out-prefix "$B/rows/hippo-best" --suffix "$tag" --header-json "$H"
    ;;
  *)
    echo "unknown setting $setting" >&2
    exit 2
    ;;
esac
