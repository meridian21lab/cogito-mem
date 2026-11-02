#!/bin/bash
# Installs the embedder hippo's benchmark scripts load (no package scripts) and fetches its fp32 weights.
set -euo pipefail
B=/private/tmp/claude-501/-Users-ksirg-devel-cogito-mem/2f8e80c5-f08b-4456-93a3-d17ec6ff8ff3/scratchpad/rivals-m
S=/Users/ksirg/devel/cogito-mem/.claude/worktrees/agent-a1f6d0361068c1fe3/scripts/rivals_m
bash "$B/adapters/sync.sh"
cp "$S/hippo_best.mjs.txt" "$B/hippo/repo/benchmarks/longmemeval/rivals_best.mjs"
env -i npm_config_cache="$B/hippo/npm-cache" npm_config_userconfig=/dev/null PATH=/usr/local/bin:/usr/bin:/bin npm --prefix "$B/hippo/repo" install --no-save --ignore-scripts --no-audit --no-fund @huggingface/transformers@4.2.0 2>&1 | tail -1
grep -m1 '"version"' "$B/hippo/repo/node_modules/@huggingface/transformers/package.json"
ls "$B/hippo/repo/node_modules/onnxruntime-node/bin/napi-v6/darwin/arm64" | head -3
REV=751bff37182d3f1213fa05d7196b954e230abad9
M=$B/hippo/models/Xenova/all-MiniLM-L6-v2
mkdir -p "$M/onnx"
for f in config.json tokenizer.json tokenizer_config.json onnx/model.onnx; do
  /usr/bin/curl -fsSL -o "$M/$f" "https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/$REV/$f"
done
ls -la "$M/onnx" | tail -1 | cut -c1-90
shasum -a 256 "$M/onnx/model.onnx" | cut -c1-64
