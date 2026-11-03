# LoCoMo: Cogi next to Hindsight, Mem0 and Honcho, one judge

Internal note, 1 Nov 2026. Same 1,540 questions, all answers judged by GPT-5 mini under both Mem0 prompts. Share = the
score divided by the score of reading the whole conversation. Result files: `results/comparison-2026-11/`.

**These results won't settle the competitor question.** At about 20k tokens, modern models score about the same with any
memory. The test that can separate systems is the long-history plan (1M+ tokens, with rivals), in
`research_notes/long_history_eval_strategy_20261101.md`.

## Short version

- **At 1,000 tokens, Cogi and Hindsight are level under the lenient judge.** All four paired differences include zero.
- **Under the stricter judge, Hindsight is ahead.** It wins by 2.2 and 3.0 points on two of the four models; the other two
  are too close to call. So "level" holds for the 2026 judge only.
- **At larger budgets, Cogi at 5,000 beats Hindsight at 4,096 on three of four models**, by 1.8 to 4.6 points. Cogi reads
  about 27 % more tokens there, and this setting (`top_k` 300) is above what the 0.2.1 API accepts, so it isn't a released
  setting.
- **Cogi is much faster and lighter.** It answers a search in 9.5 ms against 1.3 s, and loads all ten conversations in 17 s
  with no LLM, against about 2.4 hours of processing and $3.44-4.88 of LLM calls.
- **Mem0's and Honcho's scores come with caveats** (below): different answering models and prompts, far more text read,
  and in Mem0's files a re-run of failed questions.

## Same answering models: Hindsight and Cogi

Score (share of that model's whole-conversation score). "2026" and "2025" are the judge prompts.

| Model, judge | Whole conversation | Cogi 1,000 | Hindsight 1,000 | Hindsight 4,096 (its default) | Cogi 5,000, `top_k` 300 |
|---|---|---|---|---|---|
| GPT-5 mini, 2026 | 94.09 | 89.35 (95.0 %) | 89.09 (94.7 %) | 90.91 (96.6 %) | 93.51 (99.4 %) |
| GPT-5 mini, 2025 | 90.84 | 83.05 (91.4 %) | 85.26 (93.9 %) | 88.12 (97.0 %) | 89.94 (99.0 %) |
| Haiku 5.5, 2026 | 94.48 | 89.87 (95.1 %) | 89.68 (94.9 %) | 91.88 (97.2 %) | 94.22 (99.7 %) |
| Haiku 5.5, 2025 | 92.27 | 83.31 (90.3 %) | 84.61 (91.7 %) | 87.73 (95.1 %) | 91.17 (98.8 %) |
| gpt-oss-120b, 2026 | 89.03 | 85.65 (96.2 %) | 86.95 (97.7 %) | 89.29 (100.3 %) | 89.42 (100.4 %) |
| gpt-oss-120b, 2025 | 82.47 | 78.44 (95.1 %) | 81.43 (98.7 %) | 84.55 (102.5 %) | 83.57 (101.3 %) |
| Qwen3, 2026 | 92.47 | 88.12 (95.3 %) | 87.21 (94.3 %) | 89.29 (96.6 %) | 93.25 (100.8 %) |
| Qwen3, 2025 | 87.34 | 80.06 (91.7 %) | 80.26 (91.9 %) | 83.83 (96.0 %) | 88.44 (101.3 %) |

Mean prompt tokens per question, GPT-5 mini: whole conversation 27,602; Cogi 1,000 2,966; Hindsight 1,000 2,741; Hindsight
4,096 6,607; Cogi 5,000 8,405. Other models differ, but the order is the same.

Shares above 100 % are noise around the whole-conversation score, not a real gain. An audit of LoCoMo found 99 of the 1,540
gold answers wrong, so a perfect system scores about 93.6 %.

### Paired differences

Hindsight minus Cogi, in points, with 95 % bootstrap intervals over the same questions. **Bold** intervals exclude zero.

| Model | 1,000 v 1,000, 2026 | 1,000 v 1,000, 2025 | Hindsight 4,096 v Cogi 5,000, 2026 | Hindsight 4,096 v Cogi 5,000, 2025 |
|---|---|---|---|---|
| GPT-5 mini | -0.26 (-2.08, 1.56) | **+2.21 (0.13, 4.29)** | **-2.60 (-4.03, -1.17)** | **-1.82 (-3.44, -0.19)** |
| Haiku 5.5 | -0.19 (-1.88, 1.56) | +1.30 (-0.71, 3.38) | **-2.34 (-3.64, -1.04)** | **-3.44 (-5.00, -1.95)** |
| gpt-oss-120b | +1.30 (-0.58, 3.18) | **+2.99 (0.78, 5.13)** | -0.13 (-1.69, 1.43) | +0.97 (-0.84, 2.86) |
| Qwen3 | -0.91 (-2.79, 0.97) | +0.19 (-2.08, 2.47) | **-3.96 (-5.45, -2.47)** | **-4.61 (-6.43, -2.79)** |

No correction for the many comparisons, so an interval that only just excludes zero is weak evidence. The right-hand
columns compare unequal budgets; we did not run either system at the other's.

### Cost and speed on this Mac

| | Cogi 0.2.1 | Hindsight 1.1.0 |
|---|---|---|
| Search, median / p95, one at a time | 9.5 / 9.8 ms (1,540 questions, 1,000 tokens) | 1,308 / 1,619 ms at 1,000; 1,321 / 1,633 ms at 4,096 (100 questions) |
| Load all ten conversations | 17 s, no LLM | about 8,700 s of processing (42 min, 5 at a time) |
| LLM at load | none | 1,272 calls: 644 fact extraction, 623 consolidation, 5 dedup |
| Load cost | $0 | $3.44, or $4.88 if thought tokens are billed separately |
| Stored data, ten conversations | 6.4 MB | 303 MB (Postgres instance) |
| Memory while serving (RSS) | about 600 MB (Python 62 MB, llama-server 532 MB) | about 1.85 GB (API server 1.3 GB, Postgres 531 MB) |
| Installed | 29 MB environment, 296 MB model, 31 MB llama.cpp | 1.9 GB environment, 225 MB models, 36 MB Postgres |

Hindsight's load also stores something Cogi doesn't: 3,781 extracted facts and observations from the raw turns. That work
may be why it does better under the stricter judge at 1,000 tokens; we haven't tested that. RSS leaves out any GPU memory.
Cogi's load figures come from fresh stores, with every turn embedded.

## Other systems' published answers, rejudged

These answers come from the vendors' own result files. Answering model, prompt and context all differ from ours, so these
scores can't be paired with the table above.

| System | 2026 judge | 2025 judge | Share, 2026 / 2025 | Published | Answering model, what it read |
|---|---|---|---|---|---|
| Mem0 platform, top 200 | 92.14 | 86.95 | 97.9 / 95.7 % of GPT-5 mini whole* | 91.56 | GPT-5, 200 memories |
| Mem0 platform, top 50 | 83.64 | 76.88 | 88.9 / 84.6 % of GPT-5 mini whole* | 82.66 | GPT-5, 50 memories |
| Honcho | 93.38 | 89.55 | 103.9 / 107.2 % of its own whole-conversation run | 89.9 | Haiku 4.5, about 47K input tokens per question |
| Honcho's whole-conversation run | 89.87 | 83.57 | baseline | | Haiku 4.5, its own prompt |

\* Mem0 publishes no whole-conversation run. The denominator is GPT-5 mini's, one model down from what Mem0 used, so the true
share is probably somewhat lower or close to this. A full GPT-5 run would cost about $18, more than the credit left, so we
didn't run it.

- **Mem0's files include re-runs of questions that had failed, it appears.** Their metadata lists 156 of 1,540 questions (top
  200) and 274 (top 50) as `merged_from_questions`. By Mem0's own judge, every question outside that list scores 100 %, and
  those on it score 16.7 % and 2.6 %. The files don't explain the list, but the pattern fits retrying failures and keeping
  the second answer, which raises a score. Counting the 26 and 7 questions on the list that Mem0's judge passes as failed gives
  90.45 / 85.52 (top 200) and 83.18 / 76.56 (top 50). This is an inference from the files, not something Mem0 states.
- **Honcho's share above 100 % isn't a win over reading everything.** Its baseline uses an older model and its own prompt, and
  it scores below our Haiku 5.5 whole-conversation run (94.48 / 92.27). Against that run, Honcho's share is 98.8 / 97.1 %.
  Its 47K input tokens per question are also more than our whole-conversation prompts (27,600-41,200 tokens).
- **Their speed isn't comparable to ours.** Mem0's file records a median search of 3,055 ms (top 200) and 916 ms (top 50), on
  its hosted platform and over a network.

## How Hindsight was set up

- **Licence:** MIT (1.1.0 wheel metadata and `LICENSE`). The only other licence flagged in its dependencies was psycopg2-binary, LGPL with exceptions.
  It ran in its own environment, so nothing was added to cogito-mem's dependencies. Bound to localhost; telemetry off.
- **Load:** one retain per session in date order, in the format of Hindsight's own benchmark. LLM: GPT-5 mini, reasoning low,
  through OpenRouter. All ten conversations loaded with no failures.
- **Search:** API defaults (`budget` mid, all memory types, no chunks), `max_tokens` 1,000 and 4,096, `query_timestamp` set to the
  last session. Every answering model read the same saved results.
- **Not its best published setup.** Its own LoCoMo benchmark uses `budget` high, 32,768 tokens plus 16,384 of chunks, and
  observations off. We kept the product's defaults, as the brief asked for its default budget. Its 1,000-token result reads a
  little less than ours: about 2,741 prompt tokens against 2,966.
- **Token counts differ between systems.** Each one counts its own budget in its own tokenizer, so compare mean prompt tokens.

## Other limits

- One run per configuration.
- Cogi's 1,000-token runs date from 19 Oct 2026 (0.1.0) and its 5,000-token runs from a later session. The 1,000-token search on
  0.2.1 returned the same mean of 998.7 tokens as those runs.
- Hindsight's search speed was sampled on 100 questions, Cogi's on all 1,540.
- Spend: $21.06 answering and judging Hindsight, $2.91 rejudging, $3.44-4.88 Hindsight's load.

## Reproduce

Commands are in `results/comparison-2026-11/run_hindsight.sh`, with `hindsight_idle_recall.py` and `cogito_idle_query.py`
for speed. Source commits for the vendors' files are in `source-commits.txt`, paired differences in `compare.log`, shares in
`shares.json`.
