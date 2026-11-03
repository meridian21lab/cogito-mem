# System-1 ranking: a small local decision model in place of, or after, the search

*Spec and measurements, 1 Nov 2026. Stage-0 arm R of [`requirements.md`](../requirements.md) §7, widened to
"System-1" decision models and to search with no embeddings at all.*

*Update, 2 Nov 2026: decided not to ship. Releases run plain hybrid search and have no option for a reranker, so that
installing stays simple; the code lives under `src/cogito_mem/evals/`, for the eval commands. The results below stand. The
hook's reranked path, with the option, is at the git tag `reranker-hook-20261102`. Where this note says `dev` carries the
option, or that the hook reranks, it describes that tag.*

**In short.** A small local System-1 model that reads the question and each candidate memory together (here
Qwen3-Reranker-0.6B, or the open Jev-style decision model vLLM-SR d3-lite, both run by llama.cpp on the same
machine) gives the largest gain any search setting has shown on 1M+ token histories so far
(`evals/baselines/long-history-20261101/`), **as a reranker on top of the hybrid search**:

- **LongMemEval_M (1.2M tokens per question), measured on the M5 Max:** every needed turn inside a 1,000-token reply
  for 75.6 % of 312 held-out questions, against 56.4 % for the shipped search (+19.2, 95 % CI 14.1 to 24.4);
  knowledge updates 60 → 96, multi-session 30 → 54. Answers from that reply: 62.0 → 70.7.
- **LoCoMo, measured here:** +8.0 points at 300 tokens (4.9 to 11.3), past the +5-point gate of `requirements.md` §7;
  multi-hop 14.9 → 23.9, temporal 60.5 → 72.1.
- **Across sessions on LongMemEval-S:** every answer session in the top 10 for 8 of 8 multi-session questions,
  against 6 of 8.
- **It does not replace the embeddings or the search.** With keyword search alone in front, it beats the shipped
  search at 300 tokens on M (+16.2, 5.4 to 28.4) but loses 16 points at 5,000 and stays below it on S: it can only reorder what
  the search found. Reading every message is 117 s a query on 19k tokens here, about 80 minutes at 1.2M.
- **Speed:** 17 s for 30 candidates on a 4-core CPU (the search: 33 ms), about 0.6 s on the M5 Max. Off by default;
  worth distilling into the search (stage 1) so the quality fits the CPU budget.
- **Settings:** the model reads the candidate alone, not the message before it (that one moves a reply above the
  answer it follows). On 20 S dev questions fusing its ranks with the search's (RRF) looked better, but on M's 158
  tuning questions with hybrid candidates its score alone beats RRF by 10.8 points at 300 tokens (3.8 to 17.7) and
  5.1 at 1,000 (1.3 to 9.5), so `replace` is the default. The keyword-candidate runs below used RRF and 30
  candidates; the hybrid runs on M used `replace` and 100.

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
per text). New code is in `src/cogito_mem/evals/system1.py`; the search is unchanged.

| Setting (`Config`) | Values | Meaning |
|---|---|---|
| `candidates` | N (default 100), or 0 | how many search candidates the System-1 model reads; 0 is a full scan of every visible item. A query can ask for its own count (`rerank`, 0 for none) |
| `rerank_context` | `own` (default), `previous`, `dated` | what it reads of a candidate: `author: text`; plus the last 300 characters of the message it answers; plus the date |
| `rerank_fusion` | `replace` (default), `rrf` | order by the model's score alone, or fuse its ranks with the search's by reciprocal rank (ties keep the search order); a full scan always uses the model's order |

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

Evaluation flags, the same for `eval longmemeval-recall`, `eval locomo` and `eval long-history run` (where the model
is the `rerank` variant, over the same loaded memory as `base`): `--system1 <gguf or URL>`,
`--system1-kind rerank|noul|choice`, `--candidates N` (0: full scan), `--rerank-context`, `--rerank-fusion`,
`--system1-cache`, `--system1-threads`. `eval longmemeval-recall --sample N [--sample-offset M] [--seed S]`
takes N questions in a seeded order that keeps the mix of question types, and whose prefixes nest.

## 4. How it was measured

The evaluation protocol of [`benchmarks.md`](../benchmarks.md), with the same data files (hashes checked:
LongMemEval-S `d6f21ea9…`, LoCoMo `79fa87e9…`), the shipped EmbeddingGemma 2 Q8_0 and the shipped search, plus
the System-1 arms, and the long-history suite of `evals/baselines/long-history-20261101/`. Nothing run here asks an
LLM: every number is retrieval against the benchmark's labels (the answer rows quoted from the M5 Max runs are the
exception, and say so).

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
  keyword arms (no embeddings) ran here on 30 to 80 questions, and the hybrid arms come from the M5 Max runs in
  `evals/baselines/long-history-20261101/` (all 500 questions), paired by `question_id`.
- **LoCoMo**: every 4th question of categories 1–4 in each of the 10 conversations (`--question-stride 4`:
  388 questions with LoCoMo's mix of categories; the first N would not keep it, since LoCoMo groups questions by
  category). The baselines also ran on all 1,536.

**Metrics.** LongMemEval as `eval longmemeval-recall` and `eval long-history run` report them, with no date cutoff
(`--as-of none`, LongMemEval's own protocol): session R@k (an evidence session in the first k), all@k (every one),
NDCG@10 and MRR, the same at the turn level (the `has_answer` turns), and the long-history suite's coverage and
reached at 300, 1,000, 2,500 and 5,000 tokens (every / at least one evidence turn in a reply of that size). LoCoMo as `eval locomo`: coverage@N, every evidence turn inside
an N-token reply. Differences are paired over the same questions, with 95 % percentile-bootstrap intervals
(5,000 resamples; `compare`'s 10,000 move the ends by a point or so).
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
- **RRF over replace, on these questions.** Fusing the model's ranks with the search's keeps the search's first
  place when the model is unsure: with `own`, +10.5 turn R@1 for every model, against −15.8 to 0 for replace.
  Letting the model break RRF ties was one question worse at both levels, so ties keep the search order. **This
  did not carry over to 1M+ tokens:** on LongMemEval_M's 158 tuning questions with hybrid candidates (top 100),
  the model's score alone beats fusion at 300 tokens by 10.8 points (95 % CI 3.8 to 17.7) and at 1,000 by 5.1
  (1.3 to 9.5), level at 2,500 (`m-ggml-*.json`, measured on the M5 Max). There the search's own order is the
  weaker signal, so `replace` is now the default; RRF stays an option for small memories.
- **Three finalists, which 20 questions cannot separate:** Qwen3-Reranker-0.6B (a relevance Noul; the fastest,
  28.7 s per query on 2 threads), d3-lite as a Noul per candidate (the best turn level, 40.8 s) and d3-lite as one
  listwise Choice over the 30 candidates (the best session level, 34.6 s), all with `own` and RRF. All three ran
  on the test questions of LongMemEval_M with keyword candidates; Qwen3-Reranker also ran on S and on LoCoMo, the
  slowest to score. d3-edge (0.59B) lost to keyword search alone and was dropped.

## 6. Results on the test questions

The System-1 arms run on this machine use the settings fixed on the dev questions: the candidate alone (`own`),
RRF, 30 candidates; the `replace` rows replay the same scores ordered by the model alone. The hybrid + reranker rows on M in §6.3 come from `evals/baselines/long-history-20261101/`
(M5 Max, top 100, `replace`). Each cell is the arm's score, then its paired difference from the row it is compared
with and the 95 % interval.

### 6.1 LongMemEval-S (about 120k tokens per question)

**This machine reproduces the published baseline exactly.** On the 29 answerable questions of the test sample,
`long-history run`'s hybrid search here gives the same value as `evals/baselines/long-history-20261101/s-full.json`
(measured on the M5 Max) for every one of R@1, R@5, all@5, all@10, coverage and reached at every budget, question by
question. The LoCoMo baselines match `benchmarks.md` too (coverage 39.1 / 56.5 / 72.5 against 39.0 / 56.5 / 72.5).

The shipped search, then the System-1 model behind it (`long-history run`, 29 answerable questions, no cutoff):

| | Session R@1 | Session all@10 | Coverage 300 | Coverage 1,000 | Coverage 2,500 | Reached 1,000 |
|---|---|---|---|---|---|---|
| Hybrid search (shipped) | 96.6 | 93.1 | 44.8 | 75.9 | 79.3 | 93.1 |
| Hybrid + Qwen3-Reranker, RRF | 96.6 (0) | **100.0 (+6.9 [0, +17.2])** | 44.8 (0) | 79.3 (+3.4 [0, +10.3]) | 79.3 (0) | 100.0 (+6.9 [0, +17.2]) |
| Hybrid + Qwen3-Reranker, `replace` (same scores) | 96.6 (0) | **100.0 (+6.9 [0, +17.2])** | **51.7 (+6.9 [−10.3, +24.1])** | 79.3 (+3.4 [0, +10.3]) | 79.3 (0) | 100.0 (+6.9 [0, +17.2]) |

The gain is all across sessions: multi-session questions with every answer session in the top 10 go from 6 of 8
to 8 of 8, and one knowledge-update question gets its evidence inside 1,000 tokens. Ordering by the model's score
alone (`replace`, the default now) also lifts coverage at 300 tokens by 6.9 points, where RRF kept the search's top.
At 29 questions none of it is outside the noise.

Without embeddings (`eval longmemeval-recall`, the 30 hybrid questions, no cutoff), against the shipped search:

| | Session R@1 | Session R@5 | Session NDCG@10 | Session MRR | Turn R@5 | Turn NDCG@10 |
|---|---|---|---|---|---|---|
| Hybrid search (shipped) | 96.7 | 100.0 | 95.5 | 97.8 | 89.7 | 66.8 |
| Keyword search alone | 83.3 (−13.3) | 96.7 (−3.3) | 88.3 (−7.1 [−15, −1]) | 89.4 (−8.4) | 79.3 (−10.3) | 62.6 (−4.2) |
| **Keyword + Qwen3-Reranker** | 93.3 (−3.3) | 100.0 (0) | 92.9 (−2.6 [−7, +1]) | 96.1 (−1.7) | 86.2 (−3.4) | 65.5 (−1.3) |

On the 40 test questions, keyword + Qwen3-Reranker against keyword alone: session R@1 +10.0 [+2, +20], NDCG@10 +4.4
[+2, +7], MRR +6.7 [+2, +12], turn R@5 +5.4 [0, +14]. **The System-1 model recovers most of what the embeddings
add, but not all of it:** it can only reorder what BM25 found, so a question whose words do not appear in the
answer stays lost.

### 6.2 LoCoMo (about 19k tokens per conversation, up to 35 sessions)

388 questions (every 4th of categories 1–4, all 10 conversations), against the shipped search on the same
questions:

| | Coverage 100 | **Coverage 300** | Coverage 1,000 | All evidence in the top 10 |
|---|---|---|---|---|
| Hybrid search (shipped), same questions | 36.1 | 54.4 | 74.0 | 55.2 |
| Hybrid + Qwen3-Reranker | 42.8 (+6.7 [+3.6, +9.8]) | **62.4 (+8.0 [+4.9, +11.3])** | 74.2 (+0.3 [0, +0.8]) | 65.2 (+10.1 [+7.0, +13.1]) |

Coverage at 300 tokens by category: multi-hop 14.9 → 23.9, temporal 60.5 → 72.1, single-hop 68.9 → 75.6,
open-domain 19.2 → 23.1. **This is the gate of `requirements.md` §7: +5 points at 300 tokens. The reranker clears it
(+8.0; the lower end of the interval, +4.9, is at the line).** At 1,000 tokens nothing changes: a reply that size
already holds nearly all of the 30 candidates the model reorders, so the order inside it does not change what is
in it. Reordering more candidates is what could move the larger budgets.

### 6.3 LongMemEval_M (about 1.2M tokens and 4,900 messages per question)

`long-history run --search keyword` with the System-1 model as the `rerank` variant, so `base` (keyword search)
and `rerank` come from the same loaded memory. The shipped hybrid search is the published
`evals/baselines/long-history-20261101/m-final.json`, paired by `question_id`. This machine reproduces those
files exactly where it could check (S hybrid and S keyword above). Embedding M here would take about an hour a
question, so **hybrid + System-1 on M was measured on the M5 Max** (`m-rerank-heldout.json`, Qwen3-Reranker on the
top 100, the model's order alone, 312 held-out answerable questions):

| | Session R@1 | Session R@5 | Session all@10 | Coverage 300 | Coverage 1,000 | Coverage 2,500 | Coverage 5,000 |
|---|---|---|---|---|---|---|---|
| Hybrid search (shipped) | 75.0 | 94.9 | 87.2 | 39.4 | 56.4 | 70.8 | 81.7 |
| **Hybrid + Qwen3-Reranker** | **86.2** | 96.8 | **91.7** | **59.3** | **75.6** | **84.3** | **88.5** |

Coverage at 1,000: +19.2 (95 % CI 14.1 to 24.4). By type, coverage at 1,000 goes from 60 to 96 on knowledge
updates, 30 to 54 on multi-session questions, 37 to 58 on preferences and 60 to 68 on temporal reasoning. Answered
by Claude Haiku 5.5 from the reply alone (334 held-out questions, GPT-5 mini judging): 62.0 → 70.7 at 1,000 tokens
(+8.7, 4.2 to 13.5), and reranked 2,500 tokens match plain search at 5,000 (77.5 against 76.1) at half the tokens.
With the real `memory_query` tool, where the model can search again, there is no gain (76.6 → 76.9).

No other search setting in that folder moves coverage at 1,000 on M by more than 2 points (session boost −1.9,
exact-identifier lane −0.2). This is where the System-1 model belongs: **on top of the hybrid search, when one small reply must do.** The runs on this machine below ask
the other question, whether it can replace the embeddings.

**Instead of embeddings: keyword search + Qwen3-Reranker, 74 answerable questions** (80 test questions; 30
candidates, RRF; no date cutoff):

| | Session R@1 | Session all@10 | Coverage 300 | Coverage 1,000 | Coverage 2,500 | Coverage 5,000 | Reached 1,000 |
|---|---|---|---|---|---|---|---|
| Hybrid search, shipped (published) | 75.7 | 87.8 | 32.4 | 55.4 | 70.3 | 82.4 | 85.1 |
| Keyword search alone | 68.9 | 75.7 | 36.5 | 54.1 | 62.2 | 66.2 | 71.6 |
| **Keyword + Qwen3-Reranker** | 77.0 | 82.4 | **43.2** | **62.2** | 63.5 | 66.2 | 79.7 |
| … minus keyword alone | +8.1 [0, +16.2] | +6.8 [+1.4, +13.5] | +6.8 [+1.4, +13.5] | **+8.1 [+2.7, +14.9]** | +1.4 [0, +4.1] | 0 | +8.1 [+2.7, +14.9] |
| … minus the shipped hybrid | +1.4 [−9.5, +12.2] | −5.4 [−10.8, −1.4] | **+10.8 [+1.4, +21.6]** | +6.8 [−4.1, +17.6] | −6.8 [−14.9, 0] | **−16.2 [−24.3, −8.1]** | −5.4 [−14.9, +4.1] |
| Keyword + Qwen3-Reranker, `replace` (same scores) | 79.7 | 85.1 | **48.6** | 62.2 | 64.9 | 66.2 | — |
| … minus keyword alone | +10.8 [+1.4, +21.6] | +9.5 [+2.7, +16.2] | **+12.2 [+1.4, +23.0]** | +8.1 [+2.7, +14.9] | +2.7 [0, +6.8] | 0 | — |
| … minus the shipped hybrid | +4.1 [−5.4, +13.5] | −2.7 [−8.1, +2.7] | **+16.2 [+5.4, +28.4]** | +6.8 [−4.1, +16.2] | −5.4 [−12.2, +1.4] | **−16.2 [−24.3, −8.1]** | — |

On the 47 of them in the held-out split (`split_of`), against keyword alone (RRF): coverage at 1,000 +10.6 [+2.1,
+21.3], R@1 +14.9 [+4.3, +27.7]. Replaying the same scores with `replace` (no new model run) adds 5.4 points at 300
tokens over RRF (−4.1 to +14.9) and 2.7 at all@10 (0 to +6.8): the same direction as the 158 tuning questions with
hybrid candidates.

**All three finalists on the same 29 answerable questions:**

| | Session R@1 | Session all@10 | Coverage 300 | Coverage 1,000 | Coverage 5,000 | Model time per question (2 threads, shared) |
|---|---|---|---|---|---|---|
| Hybrid search, shipped (published) | 79.3 | 86.2 | 31.0 | 58.6 | 86.2 | — |
| Keyword search alone | 62.1 | 79.3 | 34.5 | 62.1 | 72.4 | — |
| Keyword + Qwen3-Reranker | 79.3 | 82.8 | **48.3** | **65.5** | 72.4 | **27.7 s** |
| Keyword + d3-lite, Noul | **82.8** | 82.8 | 41.4 | 55.2 | 72.4 | 38.3 s |
| Keyword + d3-lite, Choice over 30 | **82.8** | 82.8 | **48.3** | 62.1 | 72.4 | 33.8 s |

What M shows:

- **On 1M+ token histories the System-1 model matters more than on S.** Behind keyword search it adds 7 to 12 points
  of coverage at 300 and 1,000 tokens (on S: −2.7 and +5.4), and with no embedding model at all it beats the shipped
  hybrid search at 300 tokens by 10.8 points with RRF and 16.2 ordered by its score alone. The published scale curve
  explains why: hybrid search loses 13 points of
  coverage at 1,000 from 129k to 1.2M tokens, because more near-miss messages crowd the top; a model that reads each
  candidate pushes them back down.
- **It cannot fix what the search did not find.** Past the 30 candidates it reorders, keyword search's list is
  worse than hybrid's: at 5,000 tokens keyword + System-1 is 16 points below the shipped search, and the session
  all@10 is 3 to 5 points below. The model only reorders; the embeddings are what find a message whose words differ.
  **System-1 replaces neither the embeddings nor the search; it is worth most on top of the hybrid search**, as
  the M5 Max run above shows: +19.2 coverage at 1,000 with hybrid candidates, against +8.1 with keyword candidates.
- **Qwen3-Reranker is the System-1 model to keep.** It has the best coverage and is the fastest. d3-lite as one
  listwise Choice is close (the same coverage at 300, better R@1; as fast on an idle machine, §7); as a Noul per
  candidate it is the slowest and loses coverage at 1,000.

### 6.4 Across sessions

Questions whose answer is spread over, or changed across, sessions. On top of the hybrid search on M (312 held-out
answerable questions, M5 Max, `m-rerank-heldout.json`), coverage at 1,000 tokens:

| LongMemEval_M, by type | Hybrid (shipped) | Hybrid + Qwen3-Reranker |
|---|---|---|
| knowledge-update | 60 | **96** |
| multi-session | 30 | **54** |
| single-session-preference | 37 | **58** |
| temporal-reasoning | 60 | **68** |

From the runs here (the M rows: the 74 keyword questions of §6.3, against the published hybrid on the same
questions; the S and LoCoMo rows: hybrid + model):

| | Hybrid (shipped) | Keyword | Keyword + Qwen3-Reranker |
|---|---|---|---|
| M multi-session (22): coverage 1,000 / all answer sessions in the top 10 | 54.5 / 90.9 | 40.9 / 72.7 | **54.5** / 81.8 |
| M knowledge-update (8): coverage 1,000 / at 300 | 25.0 / 0.0 | 62.5 / 37.5 | **87.5 / 62.5** |
| M temporal reasoning (20): coverage 1,000 / all@10 | 60.0 / 80.0 | 55.0 / 65.0 | 55.0 / 70.0 |
| S multi-session (8), hybrid + Qwen3-Reranker: all answer sessions in the top 10 | 75.0 | — | **100.0** (hybrid + model) |
| LoCoMo multi-hop (67): coverage 300 | 14.9 | 9.0 | **23.9** (hybrid + model) |
| LoCoMo temporal (86): coverage 300 | 60.5 | 60.5 | **72.1** (hybrid + model) |

The model helps most with knowledge updates (the latest of several versions of a fact) and multi-hop questions:
it reads the question and the message together (for example "where do I live now?" against "we finally moved to
Denver last week"), where neither shared words nor a vector computed without the question singles out the newest
version. It brings multi-session recall on M up to the hybrid search's level from keyword candidates, and to
every answer session in the top 10 on top of hybrid search on S. Temporal questions gain on LoCoMo and, on top of
hybrid search, on M (60 → 68), but not from keyword candidates on M, where the missing sessions are a recall
problem of the keyword search that the model cannot repair.

## 7. Speed

Measured on the idle VM, every server on 4 threads, one run at a time, each System-1 score computed for the first
time (no cache). The query time includes embedding the question and the search.

| What answers the query | LongMemEval-S, median (p95) | LoCoMo, median (p95) |
|---|---|---|
| Keyword search | 1.7 ms (1.8) | — |
| Hybrid search, shipped | **33 ms (55)** | **24 ms (29)** |
| Hybrid + Qwen3-Reranker, 10 candidates | 5.3 s (5.5) | 2.7 s (3.0) |
| Hybrid + Qwen3-Reranker, 30 candidates | 17.1 s (26.3) | 8.1 s (9.0) |
| Hybrid + d3-lite, Noul over 30 | 19.2 s (21.3) | — |
| Hybrid + d3-lite, one Choice over 30 | 16.9 s (20.7) | — |
| Qwen3-Reranker over every message (full scan, 419) | — | **117 s** (3 questions) |

A 0.6B model reads about 400 tokens a second on these 4 cores, the same in every run (6.3k tokens in 17 s, the
50k-token full scan in 117 s). The cost grows with the number of candidates, not with the size of the memory: 30
candidates cost the same on a 1.2M-token history as on a 19k one. On the M5 Max with Metal the same model takes
about 20 ms a candidate (`evals/baselines/long-history-20261101/README.md`): about 0.6 s for 30, 2 s for the
default 100. **On a CPU, 30 candidates make a query 340 to 520 times slower than the search** (8.1 s against 24 ms,
17.1 s against 33 ms), where §6 of `requirements.md` sets 100 ms.

## 8. What a System-1 model costs, and why it cannot replace the search

A pointwise System-1 model reads the question and one candidate per pass, so its cost is the tokens it reads.
Counted with Qwen3-Reranker's tokenizer and the rerank template llama.cpp builds (instruction, question,
candidate):

| | Tokens per candidate | 30 candidates | Every item (full scan) |
|---|---|---|---|
| A LongMemEval-S history (about 115k tokens of chat) | 210 | 6.3k | 181k (862 items) |
| A LoCoMo conversation (about 19k tokens) | 115 | 3.5k | 50k (419 items) |
| The 10M-token memory of the speed test (106k items) | — | — | about 22M (106k × 210) |

At about 400 tokens a second on 4 CPU cores, and 20 ms a candidate on the M5 Max:

| | 30 candidates | 100 candidates (the default) | Every item (full scan) |
|---|---|---|---|
| LongMemEval-S, CPU | 17 s (measured) | about 57 s | about 8 min (862 items) |
| LongMemEval_M, CPU | 17 s | about 57 s | **about 80 min** (about 8,600 items) |
| LongMemEval_M, M5 Max | about 0.6 s | about 2 s | about 3 min |
| 10M-token memory, M5 Max | about 0.6 s | about 2 s | **about 35 min** |

Reading every message is not a design on any machine: the search's job is exactly to make the model read 30 or
100 messages instead of thousands. The full scan was tried on three LoCoMo questions and got all three right,
which says nothing either way; at these costs it was not worth more CPU hours.

## 9. Where it could go in Cogi

`dev` already carries the reranker as an option: `COGITO_MEM_RERANKER` (a GGUF or a llama-server URL), off by
default; it reorders the top 100 by the model's score alone, a query can ask for its own count (`rerank`, 0 for
none), and the reply says when its scores are the reranker's. The hook reranks 30 so it can answer in time and
reads the score as its gate. The places a System-1 model fits, in order:

1. **Distilled into the search (stage 1 of `requirements.md` §7).** The reranker's scores on the top 100 become
   the teacher of a small head over EmbeddingGemma's outputs, which costs milliseconds. This brings the quality to
   every machine and keeps the query path within §6's 100 ms; §11 decision 8b names exactly this case.
2. **The opt-in reranker as it is, where it is fast enough.** On the M5 Max, 30 candidates take about 0.6 s and 100
   about 2 s. On a 4-core CPU the hook's 30 take about 17 s on LongMemEval-sized messages, which holds up every
   prompt: there the hook should not rerank, and `memory_query` can, because Claude asked and can wait. A time budget
   rather than a fixed count would make this safe everywhere: score candidates in search order until the budget is
   spent and leave the rest in search order.
3. **Instead of embeddings (keyword search, then the model).** One model instead of two, and better than hybrid
   search at 300 tokens on M, but worse at large budgets and on S (§6). Not worth losing what the embeddings find.
4. **Instead of search (a full scan).** Not viable: §8.

None of these sends anything off the machine: every model is a GGUF file run by the same llama.cpp, on `127.0.0.1`.

## 10. Verdict

**On the question asked:** a local System-1 model does improve recall, and most where Cogi is positioned, on
1M+ token histories and across sessions. It does so as a reranker on top of the hybrid search, not instead of it.

| Use | Quality | Speed (CPU / M5 Max) | Verdict |
|---|---|---|---|
| Reranker after hybrid search | M: coverage at 1,000 +19.2 (56.4 → 75.6), answers +8.7; LoCoMo: +8.0 at 300 (the §7 gate); S: across sessions +6.9 all@10 | 17 s / 0.6 s for 30; 57 s / 2 s for 100 | **Yes, opt-in, off the per-prompt path on a CPU** |
| Instead of embeddings (keyword, then the model) | M: +16.2 over hybrid at 300 tokens, −16 at 5,000; S: below hybrid everywhere | same as above, and no embedding model to run | No: the embeddings find what keywords miss, and the model can only reorder |
| Instead of search (read every message) | not measurable at this cost | 80 min / 3 min a query at 1.2M tokens | No |
| Jev-like decision model (d3-lite) vs relevance model (Qwen3-Reranker) | d3 Choice close on M (same coverage at 300, better R@1), Noul worse | d3 Choice as fast, d3 Noul 1.1× slower | Qwen3-Reranker; d3 stays a candidate for typed questions beyond relevance |

What to do next, in order:

1. **Keep the reranker off by default and offer it where a GPU or time allows**, which `dev` already does
   (`COGITO_MEM_RERANKER`, a query's own `rerank`, top 100, the model's score alone). On a CPU-only machine the
   hook must not use it: 17 s for 30 candidates.
2. **Stage 1 of `requirements.md` §7 is now justified**: the reranker clears the +5-point gate (LoCoMo +8.0 at
   300 tokens; M +19.2 at 1,000) and does not fit the CPU budget, which is exactly the case §11 decision 8b names.
   Distil its scores on the top 100 into a small head over EmbeddingGemma's outputs, so the quality arrives in
   milliseconds.
3. **Rerank more than 30 on LoCoMo-sized memories too**: at 30, coverage at 1,000 did not move on LoCoMo, while
   the top 100 on M moved every budget.
4. Measure a smaller relevance model (ettin-reranker-68m or -32m, Apache-2.0; its GGUFs on Hugging Face lack the
   classifier head, so ONNX for now) for the CPU path, and the reranker's latency inside the real hook on a laptop CPU.

## 11. Reproduce

Every run behind this note, with per-question rows to pair against, is in
[`evals/baselines/system1-20261101/`](../../evals/baselines/system1-20261101/README.md).

llama.cpp at commit `785322d` or later (for `/v1/systemone`), built for the CPU; the models from Hugging Face
(`ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`, which carries the rerank template, and `ggml-org/vllm-d3-lite-GGUF`):

```sh
huggingface-cli download ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF qwen3-reranker-0.6b-q8_0.gguf --local-dir models
huggingface-cli download ggml-org/vllm-d3-lite-GGUF vllm-d3-lite-Q8_0.gguf --local-dir models
export COGITO_MEM_LLAMA_SERVER=/path/to/llama-server
```

The samples: `--sample 20 --sample-offset 60` (dev) and `--sample 40` / `--sample 30` (test) of
`eval longmemeval-recall`; for `long-history`, the first 100 questions of that order written to a file in order
(positions 0–59 and 80–99, without the dev questions, for the 80-question test file), so `--limit N` takes the same
questions from S and M. Settings below are the ones these runs used (30 candidates, RRF); drop
`--candidates 30 --rerank-fusion rrf` for the current defaults (100, the model's score alone).

```sh
# dev: keyword candidates, one row of §5 (swap the model, --system1-kind, --rerank-context, --rerank-fusion)
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --sample 20 --sample-offset 60 --as-of none \
  --search keyword --system1 models/qwen3-reranker-0.6b-q8_0.gguf --candidates 30 --rerank-fusion rrf \
  --system1-cache s1-cache.sqlite3 --out dev/kw-qwen-own-rrf.json

# LongMemEval S and M, the long-history suite: base and rerank over the same loaded memory
cogito-mem eval long-history run --data s_test80.json --limit 30 --variants base \
  --system1 models/qwen3-reranker-0.6b-q8_0.gguf --candidates 30 --rerank-fusion rrf --out lh/s-hybrid-qwen.json
cogito-mem eval long-history run --data m_test80.json --limit 80 --search keyword --variants base \
  --system1 models/qwen3-reranker-0.6b-q8_0.gguf --candidates 30 --rerank-fusion rrf --out lh/m-kw-qwen.json
cogito-mem eval long-history run --data m_test80.json --limit 40 --search keyword --variants base \
  --system1 models/vllm-d3-lite-Q8_0.gguf --system1-kind choice --candidates 30 --rerank-fusion rrf --out lh/m-kw-d3choice.json
cogito-mem eval long-history compare evals/baselines/long-history-20261101/m-final.json lh/m-kw-qwen.json \
  --metric search.base.coverage.300 --metric-b search.rerank.coverage.300

# hybrid + reranker on M (needs M's embeddings: about 90 minutes on the M5 Max, far longer on a CPU)
cogito-mem eval long-history run --data longmemeval_m_cleaned.json --split heldout --variants base \
  --reranker models/qwen3-reranker-0.6b-q8_0.gguf --out m-rerank-heldout.json

# LoCoMo
cogito-mem eval locomo --data locomo10.json --question-stride 4 --system1 models/qwen3-reranker-0.6b-q8_0.gguf \
  --candidates 30 --rerank-fusion rrf --system1-cache s1-cache.sqlite3 --out s1/locomo-hybrid-qwen.json
cogito-mem eval locomo compare locomo-hybrid.json s1/locomo-hybrid-qwen.json --budget 300
```

Speed: the same commands with `COGITO_MEM_THREADS=4 --system1-threads 4`, no `--system1-cache`, nothing else
running; `--search keyword --candidates 0` for the full scan. Each result file's `meta` records the settings, the
commit, the machine and the dataset hash.
