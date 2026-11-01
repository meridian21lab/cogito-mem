# Long-history baseline, 1 Nov 2026

Numbers to compare a new recall idea against. Everything here comes from public benchmarks and was measured on one
MacBook Pro (M5 Max, 18 cores). These are working results, not published claims: the tuning figures may move, and nothing
here has run on the held-out split yet.

## What to compare with

| | |
|---|---|
| Code | `dev`; session retrieval on M ran at `b904848`, the arms on M at `59ce22d`, the S arms at `a3b534b` |
| Embedding model | EmbeddingGemma 2 Q8_0 in llama.cpp |
| LongMemEval-S | `longmemeval_s_cleaned.json`, sha256 `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`, 114k-128k tokens per question (chars/4) |
| LongMemEval_M | `longmemeval_m_cleaned.json`, sha256 `9d79e5524794a2e6900a3aa9cb7d9152c5a3e8319c9a87c25494ba1eacee495f`, 1.13M-1.30M tokens, about 480 sessions per question |
| Both files | <https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned> |
| Answers | Claude Haiku 5.5, graded by GPT-5 mini with LongMemEval's judge prompts (LongMemEval itself uses gpt-4o) |

**To compare, use the same model, the same dataset hash, the same cutoff and the same split.** Pair by `question_id` with
`cogito-mem eval long-history compare`. Every `.json` here holds per-question rows. A run with a different embedder or
with `--search keyword` compares only with the keyword rows below.

## Session retrieval on 1M+ tokens (`m-recall-b904848.json`)

Hybrid search, no date cutoff (LongMemEval's own protocol), all 500 questions. R@k: an answer session is in the top k.
all@k: every answer session is. The paper's best on M is 0.762 at R@5, but with user turns only and LLM-extracted keys.

| Questions | n | R@1 | R@5 | R@10 | all@5 | all@10 |
|---|---|---|---|---|---|---|
| All | 500 | 74.4 | **93.0** | 96.0 | 76.0 | 85.0 |
| Answerable | 470 | 74.9 | 93.4 | 96.2 | 77.7 | 85.7 |
| single-session-user | 64 | 67.2 | 93.8 | 98.4 | 93.8 | 98.4 |
| single-session-assistant | 56 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| single-session-preference | 30 | 33.3 | 70.0 | 80.0 | 70.0 | 80.0 |
| multi-session | 121 | 71.9 | 95.9 | 97.5 | 58.7 | 74.4 |
| temporal-reasoning | 127 | 71.7 | 89.8 | 93.7 | 70.9 | 78.0 |
| knowledge-update | 72 | 90.3 | 100.0 | 100.0 | 93.1 | 98.6 |

Turn level on the 470 answerable: R@1 43.2, R@5 74.5, R@10 85.3, all@10 61.3. Query median 12.7 ms, load from a filled cache 4.6 s.
**The same search on S gives R@5 98.9 on 470 answerable, so going from about 120k to about 1.2M tokens costs about 5.5 points at
R@5 and about 9 at all@10.** Preference questions are the weakest.

## Search, hook and recency on 1M+ tokens (`m-final.json`)

470 answerable questions, no date cutoff. Reached: at least one evidence turn is in the reply. Coverage: every evidence turn is.
The split is by a hash of the question id; no setting here was chosen on M's held-out questions.

| Budget | 300 | 1,000 | 2,500 | 5,000 |
|---|---|---|---|---|
| Search, reached | 63.2 | 80.9 | 90.0 | 93.8 |
| Search, coverage | 38.3 | 56.4 | 70.0 | 81.1 |
| Coverage on the 312 held-out answerable | 39.4 | 56.4 | 70.8 | 81.7 |
| Coverage as of the question date | 35.7 | 52.1 | 64.9 | 74.9 |
| Last N tokens, no memory | 0.0 | 0.0 | 0.0 | 0.0 |

| Hook design | Fired | Evidence turn in its items | All | Answer session | Tokens when fired |
|---|---|---|---|---|---|
| Shipped | 74.9 | 43.4 | 25.3 | 62.8 | 264 |
| Pointers (8 lines) | 84.0 | 59.2 | 40.6 | 73.2 | 331 |
| Hybrid (3 longer lines, 5 short) | 84.0 | 59.2 | 40.6 | 73.2 | 476 |

Hybrid minus shipped: +15.7 points on an evidence turn (95 % CI 12.1 to 19.6), +10.4 on the session (7.0 to 14.0). Pointers and
hybrid have the same items and differ in how much of each arrives without opening. In these rows "in its items" is not "in the text".

Other search settings, paired against plain search on M (`m-full.jsonl` logic, commit `0542ef4`): session boost changes coverage at 1,000 by
−1.9 (−3.6 to −0.2) and at 5,000 by −0.2 (−1.7 to +1.1). The exact-identifier lane changes it by −0.2 (−1.1 to +0.4). Both stay off.

**The same 158 questions as the history grows** (`m-scale-*.json`, tuning split, sessions kept at random plus the evidence sessions):

| Sessions | Tokens (chars/4) | R@5 | all@10 | Coverage 1,000 | 2,500 | 5,000 |
|---|---|---|---|---|---|---|
| 50 | 129k | 98.7 | 93.7 | 69.6 | 82.3 | 89.2 |
| 100 | 256k | 96.2 | 91.1 | 69.0 | 80.4 | 88.6 |
| 250 | 634k | 94.3 | 88.6 | 62.7 | 74.7 | 84.2 |
| about 480 | 1.2M | 90.5 | 82.9 | 56.3 | 68.4 | 79.8 |

## Search, delivery and recency on S (`s-full.json`, `s-keyword.json`)

470 answerable questions, no date cutoff. Coverage: every evidence turn is in the reply at that budget.

| Arm | R@1 | R@5 | R@10 | all@10 | Coverage at 300 | 1,000 | 2,500 | 5,000 |
|---|---|---|---|---|---|---|---|---|
| Hybrid search | 92.8 | 98.9 | 99.4 | 94.9 | 45.1 | 70.4 | 81.3 | 87.2 |
| Hybrid + exact-identifier lane | 92.8 | 98.9 | 99.4 | 94.9 | 45.5 | 70.2 | 81.1 | 87.2 |
| Hybrid + session boost | 93.0 | 98.9 | 99.4 | 94.7 | 44.7 | 69.4 | 81.5 | 88.7 |
| Keyword only | 85.5 | 95.3 | 98.3 | 89.1 | 45.1 | 63.8 | 73.6 | 78.9 |
| Last N tokens, no memory | | | | | 0.0 | 0.2 | 1.5 | 2.8 |

The hook, unasked, for the same questions:

| Design | Fired | An evidence turn reached | All reached | Answer session reached | Tokens when fired |
|---|---|---|---|---|---|
| Shipped, 300 tokens | 72.1 | 47.4 | 27.7 | 69.4 | 248 |
| 8 pointers | 93.2 | 73.6 | 52.1 | 86.6 | 350 |

As of the question date, which hides evidence dated later that day, search drops to R@5 95.1 and coverage 41.1 / 64.0 / 73.8 / 79.4.

## Answers on S, tuning split (166 questions)

Tuning only, and a small sample: differences under about 10 points can be noise. Answering from each arm's text with no tools:

| Arm (`s-answer-tuning-haiku-*.json`) | J | Context tokens |
|---|---|---|
| Search, 5,000 tokens | 75.3 | 5,996 |
| Search, 1,000 tokens | 68.7 | 1,230 |
| Shipped hook text alone | 36.8 | 166 |
| Pointer lines alone, not opened | 32.5 | 211 |
| Last 5,000 tokens, no memory | 12.0 | 5,719 |

With the real `memory_query` and `memory_open` tools and the hook's text in the prompt (`s-agent-tuning.json`, cost $0.78). The system prompt
carries the MCP instructions, so the model searches far more than Claude was seen to in real use: this tests the path, not the habit.

| Arm | J | Evidence read | Searched | Opened | Prompt tokens |
|---|---|---|---|---|---|
| Pointers + tools | 75.9 | 88.9 | 68 | 67 | 12,392 |
| Tools only | 74.1 | 87.7 | 99 | 0 | 12,970 |
| Shipped hook + tools | 72.3 | 82.7 | 73 | 0 | 10,310 |

With `memory_query` reading 2,500 tokens by default (`s-agent-tuning-q2500.json`): tools only 78.3, pointers 78.9, at 19,312 and 17,059 prompt tokens.
Pointers here are the earlier gate (`a3b534b`). The 5,000-token run stopped at OpenRouter's budget, so it is not here.

## Whole conversation past the limit (`full-context-*.json`)

Real history text sent to each model, with compression off. Every M history is over 1M tokens by chars/4; no S history is.

| Model | Limit in its refusal | Largest accepted here (chars/4) | Billed tokens |
|---|---|---|---|
| Claude Haiku 5.5, Sonnet 5.5 | 1,000,000 | 500k | 675,259 |
| GPT-5 mini | 400,000 | 260k | 215,516 |
| Qwen3-235B | 262,144 | 130k | 111,206 |
| gpt-oss-120b | 131,072 | none (130k was 131,745) | |

This removes one baseline and says nothing about Cogi's quality. Long histories can also be read in several requests.

## LoCoMo, for scale (about 19,400 tokens per conversation)

`mem0-2026` protocol, 1,540 questions, GPT-5 mini judge. See `docs/benchmarks.md`.

| Model | Search, 1,000 | Search, 5,000 (`top_k` 300) | Whole conversation |
|---|---|---|---|
| Claude Haiku 5.5 | 89.9 | 94.2 | 94.5 |
| GPT-5 mini | 89.4 | 93.5 | 94.1 |
| Qwen3-235B | 88.1 | 93.3 | 92.5 |
| gpt-oss-120b | 85.6 | 89.4 | 89.0 |

## Not here yet

- **Answers on M.** The contexts are ready but OpenRouter's monthly budget ran out before they could be graded.
- Rival memories on M, and whole-context tests under the limit.
- Real-session results: the private probes stay out of this public repo.
- The reranker arm.

## Reproduce

```sh
cogito-mem eval longmemeval-recall --data longmemeval_m_cleaned.json --as-of none --out m-recall.json
cogito-mem eval long-history run --data longmemeval_s_cleaned.json --variants base,exact,session,exact+session --contexts-out s-contexts.jsonl --out s-full.json
cogito-mem eval long-history run --data longmemeval_s_cleaned.json --search keyword --variants base,exact --out s-keyword.json
cogito-mem eval long-history answer --contexts s-contexts.jsonl --arm search-5000 --split tuning --env-file .env --out a.json
cogito-mem eval long-history agent --data longmemeval_s_cleaned.json --split tuning --env-file .env --arms tools-only,shipped,pointers --out g.json
cogito-mem eval long-history run --data longmemeval_m_cleaned.json --variants base --contexts-out m-contexts.jsonl --out m-final.json
cogito-mem eval long-history run --data longmemeval_m_cleaned.json --split tuning --sessions 250 --variants base --out m-scale-250.json
cogito-mem eval long-history compare m-final.json new.json --metric search.base.coverage.1000
cogito-mem eval long-history compare m-final.json --metric delivery.shipped.any --metric-b delivery.hybrid.any
```

Embedding M from nothing took about 90 minutes on this Mac and leaves a 537 MB cache; `--cache` keeps it apart from a live one.
A machine without a GPU will take far longer. Hooks stay on the shipped design unless `COGITO_MEM_RECALL_DESIGN` is `pointers` or `hybrid`.
