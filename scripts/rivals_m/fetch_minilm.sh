#!/bin/bash
# Fetches the q8 MiniLM weights agentmemory's local provider loads, into its own cache folder.
set -euo pipefail
M=/private/tmp/claude-501/-Users-ksirg-devel-cogito-mem/2f8e80c5-f08b-4456-93a3-d17ec6ff8ff3/scratchpad/rivals-m/agentmemory/repo/node_modules/@huggingface/transformers/.cache/Xenova/all-MiniLM-L6-v2
mkdir -p "$M/onnx"
REV=$(/usr/bin/curl -fsSL https://huggingface.co/api/models/Xenova/all-MiniLM-L6-v2 | /usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin)['sha'])")
echo "revision $REV"
for f in config.json tokenizer.json tokenizer_config.json onnx/model_quantized.onnx; do
  /usr/bin/curl -fsSL -o "$M/$f" "https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/$REV/$f"
done
ls -la "$M/onnx" | tail -1 | cut -c1-90
shasum -a 256 "$M/onnx/model_quantized.onnx" | cut -c1-64
