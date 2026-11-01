# System-1 ranking: a small local decision model in place of, or after, the search

*Spec and measurements, 1 Nov 2026. Stage-0 arm R of [`requirements.md`](../requirements.md) §7, widened to
"System-1" decision models and to search with no embeddings at all.*

<!-- RESULTS-SUMMARY -->

**Checked on 1M+ tokens, later on 1 Nov 2026.** On LongMemEval_M's 158 tuning questions, Qwen3-Reranker (ggml-org, top 100) ordered by its score alone
beats rank fusion at small budgets: every needed turn in the reply for 59.5 % against 48.7 % at 300 tokens (−10.8, 95 % CI −17.7 to −3.8), 74.7 %
against 69.6 % at 1,000 (−5.1, −9.5 to −1.3), level at 2,500, and 82.3 % against 83.5 % at 5,000. So `rerank_fusion` now defaults to `replace`.
The numbers below are from when `rrf` was the default, on smaller histories.

## 1. The idea

Cogi finds memories by words (BM25) and meaning (EmbeddingGemma 2) and fuses the two lists. Neither reads the
question and a memory together: the vector of "What did we call the staging server?" is computed without ever
seeing the message *Let's call it "acorn"*. A **System-1 model** does read them together and answers in one
forward pass, with a probability and no generated text. The proposal tested here:

1. **As a re-ranker.** The search proposes its top N; the System-1 model scores each against the question and
   the order follows its score.
2. **Instead of embeddings.** Keyword search (no embedding model) proposes the top N; the System-1 model ranks
   them. One model instead of two.
3. **Instead of search.** The System-1 model scans every message in the SQLite store (or a subset) and picks the
   relevant ones.

The inspiration is TypeSafe's **Jev**, "the first System One model": a request is a `state` plus named, typed
questions (*Noul*: the probability a statement holds; *Choice*: a probability for each of up to 255 options;
*Score*), answered with probabilities in one pass. Jev is hosted only (OpenRouter), and Cogi keeps everything on
the user's machine, so **only open-weight models run by llama.cpp on the same machine are considered**. No
request leaves `127.0.0.1`.

## 2. Open replacements for Jev

Checked on 1 Nov 2026 against Hugging Face and the llama.cpp source (commit `785322d`).

**llama.cpp now serves the Jev API itself.** `POST /v1/systemone` (`tools/server/server-decision.cpp`) takes
TypeSafe's `state` + `questions` with `choice`, `noul` and `score`, for GGUF "decision models" that carry
`<arch>.decision.*` metadata: openjev, lev, kev, nimble, laya, clef, pplx-decider, vllm-decision2, vllm-d3,
lfm2-d1, granite-switch, h2o-lightning and others. A Choice can carry up to 255 options for most of them. So a
Jev-shaped System-1 call runs locally, in the runtime Cogi already ships.

| Model | Size | Licence | How llama.cpp serves it | Role here |
|---|---|---|---|---|
| **Qwen3-Reranker-0.6B** (`ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`) | 0.6B | Apache-2.0 | `--reranking`, `/v1/rerank`: softmax over the {yes, no} head, i.e. a Noul P(yes) | pointwise Noul, the reranker `requirements.md` §7 names |
| **vLLM-SR d3-lite** (`ggml-org/vllm-d3-lite-GGUF`) | 0.85B (Qwen3.5-0.8B base) | Apache-2.0 | `/v1/systemone`, native decision model, non-causal | Noul per candidate, or one Choice over all candidates |
| vLLM-SR d3-edge (`ggml-org/vllm-d3-edge-GGUF`) | 0.59B | Apache-2.0 | `/v1/systemone` | smaller d3 |
| gte-reranker-modernbert-base | 149M | Apache-2.0 | `/v1/rerank` (raw logit) | not run: a classic cross-encoder, the cheap end |
| Qwen3-Reranker-4B | 4B | Apache-2.0 | `/v1/rerank` | not run: about 7× the 0.6B's cost on a CPU |
| pplx-decider-flash v1.2 | 4.5B | Apache-2.0 | `/v1/systemone` | not run: too heavy for a laptop CPU |
| jina-reranker-v3 / v3.5 (listwise) | 0.6B | CC-BY-NC | needs a llama.cpp fork | excluded: non-commercial |
| bekko-system-one (an "open Jev") | 17M–400M | none given | — | excluded: no licence |

Two practical findings:

- **The GGUF matters.** A correct Qwen3-Reranker GGUF has `cls.output.weight` (the "yes" and "no" rows of the
  LM head), pooling type RANK, the labels `[yes, no]` and a `tokenizer.chat_template.rerank`; the converter adds
  them since llama.cpp PR #15824 (Sep 2025). Conversions from June 2025 lack the head and score a clear match
  near 0, which is very likely the "0.015 for a clear match" of `requirements.md` §15 note 20. The ggml-org Q8_0
  scores *Let's call the staging server "acorn"* 1.000 and an unrelated message 0.000 for "What did we call the
  staging server?".
- **The rerank instruction is fixed.** The GGUF's template hard-codes "Given a web search query, retrieve
  relevant passages that answer the query". A custom instruction would need `/completion` with token log
  probabilities; it was not needed to get the results below.

## 3. Design

Everything goes through the `Reranker` shape `Memory` already has (`score(query, texts)` → one number in [0, 1]
per text). New code is in `src/cogito_mem/system1.py`; the search is unchanged.

| Setting (`Config`) | Values | Meaning |
|---|---|---|
| `candidates` | N, or 0 | how many search candidates the System-1 model reads; 0 is a full scan of every visible item |
| `rerank_context` | `own` (default), `previous`, `dated` | what it reads of a candidate: `author: text`; plus the last 300 characters of the message it answers; plus the date |
| `rerank_fusion` | `rrf` (default), `replace` | fuse the model's ranks with the search's by reciprocal rank (ties keep the search order), or order by the model's score alone; a full scan always uses the model's order |

Scorers (`system1.start_system1(spec, kind)`):

- **`rerank`**: `llama-server --reranking`, `POST /v1/rerank` with the question and the N candidate texts.
- **`noul`**: `POST /v1/systemone`, one Noul per candidate. State `{"question": …, "message": …}`; instructions
  "Does the message contain information that helps answer the question, even partly? The message is from the
  user's earlier conversations with an AI assistant." Four requests at a time keep the server's slots busy.
- **`choice`**: `POST /v1/systemone`, one Choice whose options are the N candidates (keys `"1"`…`"N"`, the
  descriptions are the texts); state `{"question": …}`. One forward pass returns a probability per candidate.
  For d3 the whole prompt is one batch, so the server runs with `-ub 16384`.

`CachedRanker` keeps scores in SQLite, keyed by model, question and text (and, for a Choice, the whole option
list): an evaluation asks each question at several budgets, and reruns with another fusion cost nothing.

Evaluation flags, the same for `eval longmemeval-recall` and `eval locomo`: `--system1 <gguf or URL>`,
`--system1-kind rerank|noul|choice`, `--candidates N` (0: full scan), `--rerank-context`, `--rerank-fusion`,
`--system1-cache`, `--system1-threads`. `eval longmemeval-recall --sample N [--sample-offset M] [--seed S]`
takes N questions in a seeded order that keeps the mix of question types, and whose prefixes nest.

## 4. How it was measured

The evaluation protocol of [`benchmarks.md`](../benchmarks.md), with the same data files (hashes checked:
LongMemEval-S `d6f21ea9…`, LoCoMo `79fa87e9…`), the shipped EmbeddingGemma 2 Q8_0 and the shipped search, plus
the System-1 arms. No LLM answers or judges anything: every number is retrieval against the benchmark's labels.

| | |
|---|---|
| Machine | a cloud VM: 4-core Intel Xeon @ 2.1 GHz (AVX-512, AMX), 15 GB, **no GPU**; Python 3.13 |
| llama.cpp | built from source, commit `785322d` (1 Nov 2026), CPU backend |
| Search | cogito-mem 0.2.1 defaults: hybrid (BM25 + EmbeddingGemma 2, RRF), items embedded with author and previous message |
| System-1 models | `qwen3-reranker-0.6b-q8_0.gguf` (ggml-org), `vllm-d3-lite-Q8_0.gguf`, `vllm-d3-edge-Q8_0.gguf` (ggml-org) |
| CPU split | quality runs: the embedding server and the System-1 server on 2 threads each, side by side; speed runs: one at a time on 4 threads, nothing else running |

**Questions.** Embedding one LongMemEval-S history (about 115k tokens, about 1,000 items with their context)
takes 4–8 minutes on this CPU, against 4.7 s with Metal on the laptop of `benchmarks.md`, so the 500 questions
(about 40 CPU-hours) were sampled:

- **LongMemEval-S test sample**: the first 40 questions of a seeded order that keeps the mix of question types
  (`--sample 40 --seed 0`: 11 multi-session, 11 temporal, 6 knowledge-update, 6 single-session-user, 4
  single-session-assistant, 2 preference; 3 of them abstention). Hybrid arms ran on its first 30 (8, 8, 5, 4, 3,
  2; 1 abstention), since the order nests.
- **LongMemEval-S dev sample**: the next 20 (`--sample 20 --sample-offset 60`), disjoint from the test sample.
  Every System-1 setting (what the model reads, fusion, which model) was chosen there, with keyword candidates,
  before any test question was scored with a System-1 model.
- **LongMemEval_M** (`longmemeval_m_cleaned.json`, sha256 `9d79e552…`): the same questions as S, each with
  about 480 sessions, 4,950 turns and 1.2M tokens of history, the size Cogi is meant for (1M+ tokens across
  many sessions). Its 2.7 GB were streamed and the first 100 questions of the S order written in that order
  (`--limit 40` there is `--sample 40` on S: the same questions, ten times the history). M's histories hardly
  overlap (each question brings about 1.1M new tokens), so embedding one takes about an hour on this CPU: the
  keyword arms (no embeddings) ran on 40 to 100 questions, the hybrid arms on as many as the time allowed.
- **LoCoMo**: every 4th question of categories 1–4 in each of the 10 conversations (`--question-stride 4`:
  387 questions with LoCoMo's mix of categories; the first N would not keep it, since LoCoMo groups questions by
  category). The baselines also ran on all 1,536.

**Metrics.** LongMemEval-S as `eval longmemeval-recall` reports them, with no date cutoff (`--as-of none`,
LongMemEval's own protocol): session R@k (an evidence session in the first k), all@5, NDCG@10 and MRR, and the
same at the turn level (the `has_answer` turns). LoCoMo as `eval locomo`: coverage@N, every evidence turn inside
an N-token reply. Differences are paired over the same questions, with 95 % percentile-bootstrap intervals.
**Across sessions**: LongMemEval's multi-session questions need evidence from two or more sessions (all@k: every
one of them in the first k), and its temporal and knowledge-update questions ask about facts spread over, or
changed across, sessions; LoCoMo's multi-hop questions do the same across up to 35 sessions. These slices are
reported on their own.

## 5. Choosing the model and its settings (dev questions)

20 dev questions, keyword search proposing 30 candidates, no date cutoff. Each cell is the arm's score, then its
paired difference from keyword search alone with the 95 % interval. With 20 questions one question is 5 points
(turn level: 19 questions, 5.3 points), so only large effects show.

| Keyword top 30, then | Session R@1 | Session all@5 | Session NDCG@10 | Turn R@1 | Turn R@5 | Turn NDCG@10 | Model time per query (2 threads) |
|---|---|---|---|---|---|---|---|
| nothing (keyword search alone) | 80.0 | 80.0 | 82.9 | 57.9 | 84.2 | 63.1 | — |
| Qwen3-Reranker, previous, replace | 85.0 (+5) | 90.0 (+10) | 91.1 (+8.1 [+1, +16]) | 42.1 (−15.8) | 84.2 (0) | 65.2 (+2.1) | 37.6 s |
| Qwen3-Reranker, previous, RRF | 90.0 (+10) | 90.0 (+10) | 90.9 (+7.9 [+2, +15]) | 68.4 (+10.5) | 84.2 (0) | 71.4 (+8.3 [+2, +16]) | (cached) |
| Qwen3-Reranker, own, replace | 85.0 (+5) | 90.0 (+10) | 90.8 (+7.8 [+1, +17]) | 57.9 (0) | 89.5 (+5.3) | 70.1 (+7.0 [+1, +15]) | 28.7 s |
| **Qwen3-Reranker, own, RRF** | **90.0 (+10)** | 85.0 (+5) | 90.2 (+7.3 [+2, +15]) | **68.4 (+10.5)** | **89.5 (+5.3)** | 70.3 (+7.1 [+3, +12]) | (cached) |
| Qwen3-Reranker, dated, replace | 85.0 (+5) | 90.0 (+10) | 90.9 (+7.9) | 42.1 (−15.8) | 84.2 (0) | 64.2 (+1.1) | 40.1 s |
| d3-lite, Noul, previous, replace | 80.0 (0) | 90.0 (+10) | 87.2 (+4.3) | 36.8 (−21.1) | 78.9 (−5.3) | 56.0 (−7.2) | 46.6 s |
| d3-lite, Noul, previous, RRF | 85.0 (+5) | 90.0 (+10) | 87.3 (+4.4) | 47.4 (−10.5) | 78.9 (−5.3) | 63.1 (0) | (cached) |
| d3-edge, Noul, previous, replace | 70.0 (−10) | 90.0 (+10) | 83.1 (+0.1) | 26.3 (−31.6) | 52.6 (−31.6) | 45.5 (−17.6) | 22.3 s |
| d3-lite, Choice over 30, previous, replace | 25.0 (−55) | 60.0 (−20) | 59.9 (−23.0) | 0.0 (−57.9) | 21.1 (−63.2) | 13.5 (−49.6) | 52.9 s |
| d3-lite, Choice over 30, previous, RRF | 70.0 (−10) | 70.0 (−10) | 83.2 (+0.2) | 15.8 (−42.1) | 47.4 (−36.8) | 39.6 (−23.5) | (cached) |
| d3-lite, Noul, own, replace | 90.0 (+10) | 90.0 (+10) | 91.0 (+8.0 [+2, +15]) | 52.6 (−5.3) | 84.2 (0) | 68.8 (+5.7) | (cached) |
| **d3-lite, Noul, own, RRF** | 85.0 (+5) | 85.0 (+5) | 88.5 (+5.6 [+2, +9]) | **68.4 (+10.5)** | **89.5 (+5.3)** | **75.6 (+12.5 [+5, +21])** | 40.8 s |
| d3-lite, Choice over 30, own, replace | 80.0 (0) | 95.0 (+15) | 88.1 (+5.2) | 42.1 (−15.8) | 78.9 (−5.3) | 62.6 (−0.5) | (cached) |
| **d3-lite, Choice over 30, own, RRF** | **90.0 (+10)** | 90.0 (+10) | **91.1 (+8.2 [−1, +18])** | **68.4 (+10.5)** | 78.9 (−5.3) | 71.9 (+8.8 [+2, +16]) | 34.6 s |

What the dev questions decided:

- **What the model reads matters more than which model reads it.** With the message before each candidate
  (`previous`), the reply that follows an answer carries the answer in its context and outranks it: turn R@1
  falls 15.8 points for Qwen3-Reranker, and the native decision models fall further (d3-lite's listwise Choice
  to 0 turn R@1, its evidence turns ranked 4th to 20th). Reading the candidate alone (`own`) removes the problem
  for all three, and is 25 % cheaper. A date in front (`dated`) changed nothing.
- **RRF over replace.** Fusing the model's ranks with the search's keeps the search's first place when the model
  is unsure: with `own`, +10.5 turn R@1 for every model, against −15.8 to 0 for replace. Letting the model break
  RRF ties was one question worse at both levels, so ties keep the search order.
- **Three finalists, which 20 questions cannot separate:** Qwen3-Reranker-0.6B (a relevance Noul; the fastest,
  28.7 s per query on 2 threads), d3-lite as a Noul per candidate (the best turn level, 40.8 s) and d3-lite as one
  listwise Choice over the 30 candidates (the best session level, 34.6 s), all with `own` and RRF. All three go
  to the test questions of LongMemEval-S; LoCoMo, the slowest to score, runs Qwen3-Reranker only. d3-edge
  (0.59B) lost to keyword search alone and was dropped.

<!-- RESULTS -->

## 8. What a System-1 model costs, and why it cannot replace the search

A pointwise System-1 model reads the question and one candidate per pass, so its cost is the tokens it reads.
Counted with Qwen3-Reranker's tokenizer and the rerank template llama.cpp builds (instruction, question,
candidate):

| | Tokens per candidate | 30 candidates | Every item (full scan) |
|---|---|---|---|
| A LongMemEval-S history (about 115k tokens of chat) | 210 | 6.3k | 181k (862 items) |
| A LoCoMo conversation (about 19k tokens) | 115 | 3.5k | 50k (419 items) |
| The 10M-token memory of the speed test (106k items) | — | — | about 22M (106k × 210) |

<!-- COST -->

## 9. Where it could go in Cogi

The prompt hook adds at most 300 tokens to every prompt and must not hold the prompt up, so a System-1 model
does not belong there on a CPU. The places it could go, in order of how well they fit:

1. **Distilled into the search (stage 1 of `requirements.md` §7).** The reranker's scores on the top 30 become
   the teacher of a small head over EmbeddingGemma's outputs, which costs a few milliseconds. This keeps the
   query path at tens of milliseconds and is what §7 plans when a reranker gains enough.
2. **An opt-in reranker for searches Claude asks for** (`memory_query`), on machines with a GPU: the plugin's
   recall hook stays as it is, and `cogito-mem serve --system1 <gguf>` (today `--reranker`, `/v1/rerank` only)
   reorders the top N of explicit searches. N is bounded by a time budget, not fixed: candidates are scored in
   search order until the budget is spent, and the rest keep their search order.
3. **Instead of embeddings (keyword search, then the System-1 model).** One model instead of two, but the
   System-1 model can only reorder what BM25 found; see §6 for what that costs in recall.
4. **Instead of search (a full scan).** Not viable: §8.

None of these sends anything off the machine: the model is a GGUF file run by the same llama.cpp, on
`127.0.0.1`.

## 11. Reproduce

llama.cpp at commit `785322d` or later (for `/v1/systemone`), built for the CPU; the models from Hugging Face:

```sh
huggingface-cli download ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF qwen3-reranker-0.6b-q8_0.gguf --local-dir models
huggingface-cli download ggml-org/vllm-d3-lite-GGUF vllm-d3-lite-Q8_0.gguf --local-dir models
export COGITO_MEM_LLAMA_SERVER=/path/to/llama-server
```

Dev questions (keyword candidates; swap the model, `--system1-kind`, `--rerank-context` and `--rerank-fusion`
for the other rows of §5):

```sh
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --sample 20 --sample-offset 60 --as-of none \
  --search keyword --system1 models/qwen3-reranker-0.6b-q8_0.gguf --rerank-context own --rerank-fusion rrf \
  --system1-cache s1-cache.sqlite3 --out dev/kw-qwen-own-rrf.json
```

Test questions (drop `--system1 …` for the baselines; `--search keyword` for the arms with no embeddings;
`--system1-kind noul` or `choice` with the d3 GGUF):

```sh
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --sample 30 --as-of none \
  --system1 models/qwen3-reranker-0.6b-q8_0.gguf --system1-cache s1-cache.sqlite3 --out s1/lme-hybrid-qwen.json
cogito-mem eval locomo --data locomo10.json --question-stride 4 \
  --system1 models/qwen3-reranker-0.6b-q8_0.gguf --system1-cache s1-cache.sqlite3 --out s1/locomo-hybrid-qwen.json
cogito-mem eval longmemeval-recall compare lme-hybrid.json s1/lme-hybrid-qwen.json
cogito-mem eval locomo compare locomo-hybrid.json s1/locomo-hybrid-qwen.json --budget 300
```

Speed: the same commands with `COGITO_MEM_THREADS=4 --system1-threads 4`, no `--system1-cache`, nothing else
running; `--candidates 0` for the full scan. Each result file's `meta` records the settings, the commit, the
machine and the dataset hash.
