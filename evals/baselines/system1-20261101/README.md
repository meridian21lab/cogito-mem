# System-1 ranking, 1 Nov 2026

The per-question results behind [`docs/notes/system1_ranker_20261101.md`](../../../docs/notes/system1_ranker_20261101.md):
a small local model (Qwen3-Reranker-0.6B, or vLLM-SR's d3-lite through llama.cpp's `/v1/systemone`) reading the question
and each candidate memory. Measured on a cloud VM with 4 CPU cores and no GPU (llama.cpp `785322d`, CPU backend), with
the models from `ggml-org` on Hugging Face. Every file holds per-question rows, so any of them pairs with another, or
with `../long-history-20261101/`, by `question_id` (LongMemEval) or `sample_id` and `q` (LoCoMo).

## The questions

- **LongMemEval-S** (`longmemeval_s_cleaned.json`, sha256 `d6f21ea9…`): `eval longmemeval-recall --sample N --seed 0`
  takes N questions in a seeded order that keeps the mix of question types, and whose prefixes nest. Test: the first 40
  (hybrid runs: the first 30). Dev: `--sample 20 --sample-offset 60`.
- **The long-history files** ran on subsets written in that same order, which is why their `dataset_sha256` is not the
  original file's: `longmemeval_s_test80.json` and `longmemeval_m_test80.json` hold positions 0–59 and 80–99 (the dev
  questions left out) of the order, from the S file and from `longmemeval_m_cleaned.json` (sha256 `9d79e552…`) by
  `question_id`. `--limit N` takes the first N, so S and M runs ask the same questions over 120k and 1.2M tokens.

```python
import json
from cogito_mem.evals.longmemeval_recall import stratified_order
order = [q["question_id"] for q in stratified_order(json.load(open("longmemeval_s_cleaned.json")), 0)]
keep = order[:60] + order[80:100]
# write [q for q in <file> if q["question_id"] in keep], in the order of keep, for S and for M (stream M with ijson)
```

- **LoCoMo** (`locomo10.json`, sha256 `79fa87e9…`): all 1,536 questions for the baselines, and every 4th question of
  categories 1–4 per conversation (`--question-stride 4`, 388) for the System-1 arm.

## Files

| File | What | Pairs with |
|---|---|---|
| `dev/keyword.json`, `dev/kw-*.json` | 20 dev questions, keyword top 30, each model and setting of the note's §5 (`*-own-rrf` = own context, RRF) | each other |
| `lme-s/hybrid-none.json`, `hybrid-question.json` | the shipped hybrid search, 30 test questions, no cutoff / as of the question date | |
| `lme-s/keyword-none.json`, `keyword-question.json` | keyword search alone, 40 test questions | |
| `lme-s/keyword-qwen-none.json` | keyword + Qwen3-Reranker (own, RRF, 30 candidates), 40 test questions | `keyword-none.json`, `hybrid-none.json` |
| `long-history/s-hybrid-qwen.json`, `s-hybrid-qwen-replace.json` | `long-history run`, 30 S questions: `base` = hybrid, `rerank` = + Qwen3-Reranker (RRF / `replace`) | `../long-history-20261101/s-full.json` (identical `base`) |
| `long-history/s-kw-qwen.json` | 40 S questions: `base` = keyword, `rerank` = + Qwen3-Reranker | `../long-history-20261101/s-keyword.json` (identical `base`), `s-full.json` |
| `long-history/m-kw-qwen.json`, `m-kw-qwen-replace.json` | 80 M questions: `base` = keyword, `rerank` = + Qwen3-Reranker (RRF / `replace`, same scores) | `../long-history-20261101/m-final.json` |
| `long-history/m-kw-d3choice.json`, `m-kw-d3noul.json` | 40 / 30 M questions: + d3-lite as one Choice over 30 / a Noul per candidate | `m-final.json`, `m-kw-qwen.json` |
| `locomo/hybrid.json`, `keyword.json` | all 1,536 LoCoMo questions | `benchmarks.md` (reproduced) |
| `locomo/hybrid-qwen-stride4.json` | 388 questions, hybrid + Qwen3-Reranker (own, RRF, 30) | `locomo/hybrid.json` |
| `speed/*.json` | the idle-machine timings of the note's §7, 4 threads, scores never cached | |

The quality runs shared the CPU (the embedding server and the System-1 server on 2 threads each), so their `query_ms`
and `system1.model_ms` are slower than the `speed/` files; use those for time.

```sh
cogito-mem eval long-history compare ../long-history-20261101/m-final.json long-history/m-kw-qwen-replace.json \
  --metric search.base.coverage.300 --metric-b search.rerank.coverage.300
cogito-mem eval locomo compare locomo/hybrid.json locomo/hybrid-qwen-stride4.json --budget 300
cogito-mem eval longmemeval-recall compare lme-s/hybrid-none.json lme-s/keyword-qwen-none.json
```
