# Benchmarks: how Cogi was measured, and how to reproduce it

The short version, with charts, is on the [Results page](https://meridian21lab.github.io/cogito-mem/results.html).
This page has every number, how it was measured and the commands to reproduce it. Everything was measured on the
author's laptop (MacBook Pro, Apple M5 Max, 18 cores) with the model that ships, EmbeddingGemma 2 (Q8_0) in
llama.cpp: LoCoMo and speed on 19 Oct 2026, LongMemEval-S on 20 Oct 2026, the 2,500 and 5,000-token budgets on
1 Nov 2026. These are our own runs, not leaderboard entries.

- [At a glance](#at-a-glance)
- [Setup](#setup)
- [LongMemEval-S: finding the right session](#longmemeval-s-finding-the-right-session)
- [LoCoMo: answering from the memory](#locomo-answering-from-the-memory)
- [LoCoMo: finding the right messages](#locomo-finding-the-right-messages)
- [Speed](#speed)

## At a glance

| Test | What it measures | cogito-mem | Next to |
|---|---|---|---|
| LongMemEval-S, 500 questions | a session holding the answer is among the first 5 found; no LLM | **99.0 %** (95.0 % as of the question date) | other local memory plugins published 95.2–98.0 % (20 Oct 2026) |
| LoCoMo, 1,540 questions | gpt-4o-mini answers from 1,000 tokens of memory, gpt-4o-mini grades | **74.7 %**, 98 % of the whole-conversation score | Mem0 92 %, Mem0g 94 %, Zep 91 % of theirs (Mem0 paper) |
| LoCoMo, 1,536 questions | every turn an answer needs is in 1,000 tokens of memory | **72.5 %** | the last 1,000 tokens of the conversation: 4.2 % |
| Speed, 10M tokens | 95 % of searches finish within, laptop CPU only | **26 ms** | design target: 100 ms |

**Terms.** *R@k* (recall at k): the share of questions for which at least one session holding the answer is among the
first k found. *all@k*: every such session is. *NDCG@10*: how well the first 10 are ordered, from 0 to 1 (1: every
answer session first). *MRR*: 1 ÷ the rank of the first answer session, averaged. *p95*: 95 % of searches finish
within this time. *95 % CI*: the 95 % confidence interval (Wilson for a single score, paired bootstrap for a
difference).

## Setup

| | |
|---|---|
| Machine | MacBook Pro, Apple M5 Max (18 cores), macOS 26.5, Python 3.12 |
| Software | cogito-mem 0.2.0 for LongMemEval, 0.1.0 for LoCoMo and speed, 0.2.1 for the 1 Nov 2026 runs (they match the 0.1.0 retrieval scores at 100, 300 and 1,000 tokens to within one question); llama.cpp as `cogito-mem setup` installs it |
| Model | EmbeddingGemma 2 (308M parameters), Q8_0 GGUF; Metal unless a row says CPU only |
| Memory | a fresh one per LongMemEval question and per LoCoMo conversation; one item per message, embedded with its author and the message it replies to |
| LongMemEval data | `longmemeval_s_cleaned.json`, sha256 `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` |
| LoCoMo data | `locomo10.json` from [snap-research/locomo](https://github.com/snap-research/locomo), sha256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |
| LLM calls (LoCoMo answers only) | gpt-4o-mini through [OpenRouter](https://openrouter.ai), temperature 0, every call cached |

Each run writes its settings, versions, machine and dataset hash into the result file's `meta`, so a number can be
traced to the run that made it.

## LongMemEval-S: finding the right session

[LongMemEval](https://github.com/xiaowu0162/LongMemEval) gives each of its 500 questions a history of about 50 chat
sessions (about 115k tokens) and labels the sessions, and the turns in them, that hold the answer. The number local
memory tools publish for it is session R@5, with no LLM involved. `eval longmemeval-recall` loads each question's
history into a fresh memory (one item per turn, both roles, dated by its session) and asks the question.

It can ask in two ways:

- **`--as-of none`**: every session in the history can be found. This is LongMemEval's own retrieval protocol, and the
  one every number in the comparison below uses.
- **As of the question's date** (the default): sessions dated after the question stay hidden, as they would in use.
  This is stricter, because 44 of the 500 questions have an answer session from later the same day, and for 20 of
  them every answer session is.

All 500 questions, session level, in %:

| Search | Sessions it can find | R@1 | R@3 | **R@5** | R@10 | all@5 | NDCG@10 | MRR |
|---|---|---|---|---|---|---|---|---|
| **cogito-mem** (default: hybrid) | all (`--as-of none`) | 92.6 | 98.0 | **99.0** | 99.4 | 90.8 | 0.946 | 0.953 |
| **cogito-mem** (default: hybrid) | up to the question date | 88.8 | 94.0 | **95.0** | 95.4 | 83.0 | 0.890 | 0.914 |
| cogito-mem, keyword only | all (`--as-of none`) | 85.2 | 93.0 | 95.0 | 98.0 | 80.6 | 0.880 | 0.898 |
| cogito-mem, keyword only | up to the question date | 81.4 | 88.8 | 91.0 | 94.0 | 73.8 | 0.827 | 0.858 |

What it means:

- **5 misses in 500.** With no cutoff, an answer session is among the first five for 99.0 % of questions (95 % CI
  97.7–99.6), including all 30 abstention questions. On the 470 answerable questions it is 98.9 %.
- **The cutoff explains the gap.** Of the 23 questions hybrid search misses even in the top 10 as of the question
  date, 20 have every answer session dated after the question. 43 of the 44 questions with a late session are
  temporal-reasoning questions; that type scores 83.5 as of the question date and 97.6 with no cutoff.
- **Meaning and words together beat words alone**, as of the question date: +4.0 points of R@5 (95 % CI 2.2 to 5.8),
  +9.2 of all@5 (6.6 to 11.8) and +6.3 of NDCG@10 (4.7 to 7.9), paired over the same questions.
- **A query takes** a median of 11 ms as of the question date and 19 ms with no cutoff.

**By question type** (R@5 / all@5, in %). Every type but temporal reasoning is at 97.6 or above with no cutoff; the
date cutoff only moves temporal reasoning, the type whose answers come later the same day.

| Question type | Questions | Hybrid, no cutoff | Hybrid, as of the question date | Keyword only, no cutoff |
|---|---|---|---|---|
| single-session-user | 64 | 100 / 100 | 100 / 100 | 98.4 / 98.4 |
| single-session-assistant | 56 | 100 / 100 | 100 / 100 | 100 / 100 |
| single-session-preference | 30 | 100 / 100 | 100 / 100 | 73.3 / 73.3 |
| multi-session | 121 | 98.4 / 82.6 | 98.4 / 82.6 | 95.0 / 65.3 |
| temporal-reasoning | 127 | 97.6 / 84.2 | 83.5 / 55.9 | 94.5 / 75.6 |
| knowledge-update | 72 | 100 / 100 | 100 / 98.6 | 100 / 95.8 |
| abstention (`_abs`) | 30 | 100 / 83.3 | 93.3 / 76.7 | 90.0 / 60.0 |

Search by meaning matters most for preference questions ("what would I like…"), where the words of the question
rarely appear in the answer: 100 against 73.3 for keywords alone.

**Within a token budget.** `eval run` asks for something stricter than R@k: every turn holding the answer, inside the
reply (470 answerable questions, as of the question date, 1 Nov 2026). The share of questions covered is 20.6 % within
100 tokens, 41.1 % within 300, 63.8 % within 1,000, 74.0 % within 2,500 and 80.6 % within 5,000. These turns average
about 240 tokens, so 5,000 tokens hold only about 20 of them, well inside `top_k` 100. The session scores above have no
budget, so they do not change. Reproduce with `cogito-mem eval run --data longmemeval_s_cleaned.json --arm custom
--search hybrid --doc-context previous --doc-author --budgets 100,300,1000,2500,5000`.

**Turn level.** The same runs also score the individual messages LongMemEval marks as holding the answer (479
questions have them). With no cutoff, hybrid search puts one of them among the first five messages it returns for 85.0 %
of questions and among the first ten for 91.6 % (NDCG@10 0.656).

### Next to other memories

Each number below is the project's own published run. We checked each one against its README or benchmark document
and its scoring script on 20 Oct 2026. All use `longmemeval_s_cleaned.json` and session R@5 over all 500 questions.
None calls an LLM to retrieve, and none applies a date cutoff, so cogito-mem's comparable number is the `--as-of none`
one.

| Memory | R@5 | R@10 | What it searches | Source |
|---|---|---|---|---|
| **cogito-mem** | **99.0** | 99.4 | every turn, both roles; words (BM25) and meaning (EmbeddingGemma 2, 308M) | this page, 20 Oct 2026 |
| hippo-memory | 98.0 | | every turn; words and meaning (all-MiniLM-L6-v2) fused by RRF; best of 5 settings | [report](https://github.com/kitfunso/hippo-memory/blob/main/docs/evals/2026-09-23-longmemeval-reproduction.md), 23 Sep 2026 |
| deja-vu | 97.2 | 98.6 | whole sessions, both roles; words only | [README](https://github.com/vshulcz/deja-vu), [results](https://github.com/vshulcz/deja-vu/blob/main/docs/benchmarks/longmemeval-s-full.json), 22 Sep 2026 |
| MemPalace (raw mode) | 96.6 | | whole sessions, user turns only; meaning (all-MiniLM-L6-v2) | [BENCHMARKS.md](https://github.com/MemPalace/mempalace/blob/develop/benchmarks/BENCHMARKS.md), 14 Apr 2026 |
| iai-personal-memory-engine | 96.2 | 97.8 | whole sessions, user turns only; meaning (bge-small-en-v1.5) | [BENCHMARKS.md](https://github.com/CodeAbra/iai-personal-memory-engine/blob/main/BENCHMARKS.md), Sep 2026 |
| agentmemory | 95.2 | | whole sessions, both roles; words, and meaning of the first 512 characters (all-MiniLM-L6-v2) | [LONGMEMEVAL.md](https://github.com/rohitg00/agentmemory/blob/main/benchmark/LONGMEMEVAL.md), 8 Apr 2026 |

With 500 questions, a difference of a few misses is noise: hippo-memory's 98.0 lies inside cogito-mem's 95 % interval
(97.7–99.6) and deja-vu's 97.2 just below it, so the first three are level. This is a snapshot of published scores on
20 Oct 2026; these projects keep improving, so check their pages for newer numbers.

**Where the picture changes.**

- **On the stricter metric, gbrain is ahead.** [gbrain](https://github.com/garrytan/gbrain-evals/blob/main/docs/benchmarks/2026-05-07-longmemeval-s.md)
  reports all@5 over the 470 answerable questions: 93.19 with OpenAI's text-embedding-3-large, 95.53 with a Voyage
  cross-encoder reranker. cogito-mem's all@5 on the same 470 is 91.3. Its R@5 there is 98.9, against gbrain's 98.72.
- **Left out because they measure something else:**
  - mcp-memory-service's 86.0 is fractional recall (answer sessions found ÷ answer sessions).
  - MemPalace's 98.4 "hybrid v4" is on 450 held-out questions. Its 100 % used an LLM reranker tuned on known
    failures, which its own document calls teaching to the test.
  - Supermemory's "97 % Recall@20 with aggregation" does not define aggregation.
  - The LongMemEval paper reports retrieval only on LongMemEval_M (about 500 sessions per question), user turns only,
    all@k over 470 questions. Its best session R@5 there is 0.762 (Contriever with LLM-extracted fact keys).

### QA accuracy, the number memory services publish

Memory services publish a different number on LongMemEval-S. An LLM answers from what the memory returns, and a
judge, usually gpt-4o, grades the answer. The score depends on the answering model as much as on the memory.
cogito-mem has not run this yet.

| Memory | QA accuracy (answering model) | Source |
|---|---|---|
| Zep | 71.2 (gpt-4o), 63.8 (gpt-4o-mini) | [paper](https://arxiv.org/abs/2501.13956) |
| Supermemory | 81.6 (gpt-4o), 85.2 (gemini-3) | [hindsight-benchmarks](https://github.com/vectorize-io/hindsight-benchmarks) |
| Mastra observational memory | 84.2 (gpt-4o), 94.9 (gpt-5-mini) | [Mastra](https://mastra.ai/research/observational-memory) |
| Hindsight | 89.0 (gpt-oss-120b), 91.4 (Gemini 3 Pro) | [hindsight-benchmarks](https://github.com/vectorize-io/hindsight-benchmarks) |
| Mem0 (April 2026 platform) | 94.4 (model not named) | [docs](https://docs.mem0.ai/core-concepts/memory-evaluation) |
| Only the answer sessions, no memory | 82.4 (gpt-4o) | [Mastra](https://mastra.ai/research/observational-memory) |

### Reproduce

Download `longmemeval_s_cleaned.json` from [the dataset page](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned),
then:

```sh
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --out results/lme-recall/hybrid.json --questions-out results/lme-recall/hybrid.jsonl
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --as-of none --out results/lme-recall/hybrid-no-cutoff.json
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --search keyword --out results/lme-recall/keyword.json
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --search keyword --as-of none --out results/lme-recall/keyword-no-cutoff.json
cogito-mem eval longmemeval-recall compare results/lme-recall/keyword.json results/lme-recall/hybrid.json
```

Loading a question's history takes 4.7 s with an empty embedding cache, so the first hybrid run takes about 40 minutes
and a rerun about 3. Rerunning with the same `--questions-out` file resumes an interrupted run.

## LoCoMo: answering from the memory

This is the protocol of the [Mem0 paper](https://arxiv.org/abs/2504.19413), the one published memory systems report.
[LoCoMo](https://github.com/snap-research/locomo) has 10 long conversations. gpt-4o-mini answers each of the 1,540
questions of categories 1–4 from what the memory returns, and gpt-4o-mini then marks the answer right or wrong
against LoCoMo's gold answer. As a check on the harness, the whole conversation is scored the same way. One run per
row.

| What gpt-4o-mini reads | All 10 conversations (1,540 questions) | First 5 conversations (762 questions) |
|---|---|---|
| cogito-mem, 300 tokens | 65.3 % | 67.8 % |
| cogito-mem, 1,000 tokens | **74.7 %** | 74.7 % |
| cogito-mem, 2,500 tokens | 76.9 % | 78.1 % |
| cogito-mem, 5,000 tokens (`--top-k 300`) | 76.4 % | 77.2 % |
| The whole conversation (no memory) | not run | 76.5 % |

What it means:

- **1,000 tokens is level with the whole conversation.** On the same 762 questions the difference is −1.8 points
  (95 % CI −5.5 to +1.8). 300 tokens is 8.7 points below it (−12.5 to −4.7).
- **For gpt-4o-mini, more than 2,500 tokens adds nothing.** 2,500 is 2.3 points above 1,000 (0.5 to 4.0), and 5,000 is
  0.5 below 2,500 (−2.1 to +1.0). The memory does hand back more: every needed turn is there for 89.5 % of questions
  at 5,000 against 82.4 % at 2,500. But when they are all there, gpt-4o-mini gets fewer right, 79.4 % against 82.7 %,
  so the extra text costs what the extra turns gain. By category from 1,000 to 5,000 tokens, open-domain rises from
  44.8 to 53.1 and multi-hop from 61.7 to 67.4, while temporal falls from 69.2 to 64.5.
- **Next to the Mem0 paper.** Under the same protocol it reports 66.9 for Mem0, 68.4 for Mem0g and 66.0 for Zep (as
  Mem0 ran it), against 72.9 for the whole conversation. That is 3.6 points below our own whole-conversation run, so
  absolute scores from different harnesses are not directly comparable. The Results page therefore shows each score
  as a share of its own harness's whole-conversation score.

**As a share of the whole conversation**, the comparison the Results page shows:

| Memory | Score | Whole conversation, same harness | Share | Source |
|---|---|---|---|---|
| **cogito-mem, 1,000 tokens** | 74.7 | 76.5 | **98 %** | this page, 19 Oct 2026 |
| Mem0 with graph (Mem0g) | 68.4 | 72.9 | 94 % | Mem0 paper |
| Mem0 | 66.9 | 72.9 | 92 % | Mem0 paper |
| Zep, run by Mem0 | 66.0 | 72.9 | 91 % | Mem0 paper |
| Zep, its own rerun | 75.1 | 72.9 | 103 % | [Zep blog](https://www.getzep.com/blog/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/) |
| Plain search (RAG), best setting | 61.0 | 72.9 | 84 % | Mem0 paper |
| ChatGPT memory | 52.9 | 72.9 | 73 % | Mem0 paper |

Newer LoCoMo scores of 90 % and more that some services publish use stronger answering models, more lenient graders
or a changed question set, so they are not comparable with these.

**By question category**, cogito-mem at 1,000 tokens (all 10 conversations):

| Category | Questions | Answered right |
|---|---|---|
| single-hop | 841 | 84.5 % |
| temporal | 321 | 69.2 % |
| multi-hop | 282 | 61.7 % |
| open-domain | 96 | 44.8 % |
| **all** | **1,540** | **74.7 %** |

Single facts and dates are its strength, since every message keeps its own date. Questions that need many facts at
once are weaker, because a fixed budget runs out first. When every evidence turn was inside the 1,000 tokens (72.5 %
of questions), 85.6 % of answers were right; when one was missing, 45.7 % were. The memory's reply averaged 999
tokens, retrieval took a median of 9.4 ms, and the whole run cost $0.53 in LLM calls.

### With current models

The same 1,540 questions under `--protocol mem0-2026`, the setup in [mem0ai/memory-benchmarks](https://github.com/mem0ai/memory-benchmarks):
a step-by-step answer prompt that reads at most 200 memories, and a more lenient judge. GPT-5 mini judges every run.
Each model is also scored on the whole conversation, so its memory score can be read as a share of its own baseline.

| Answering model | 1,000 tokens | 5,000 tokens (`--top-k 300`) | Whole conversation | 5,000 minus whole conversation (95 % CI) |
|---|---|---|---|---|
| Claude Haiku 5.5 | 89.9 % | **94.2 %** | 94.5 % | −0.3 (−1.2 to +0.7) |
| GPT-5 mini | 89.4 % | **93.5 %** | 94.1 % | −0.6 (−1.7 to +0.5) |
| Qwen3-235B | 88.1 % | **93.3 %** | 92.5 % | +0.8 (−0.4 to +2.0) |
| gpt-oss-120b | 85.7 % | **89.4 %** | 89.0 % | +0.4 (−1.0 to +1.8) |

What it means:

- **These models keep gaining past 2,500 tokens.** GPT-5 mini scores 79.6 % at 300 tokens, 89.4 % at 1,000, 92.1 % at
  2,500 and 93.5 % at 5,000 (+1.4 over 2,500, 0.4 to 2.5). gpt-4o-mini stops gaining at 2,500.
- **5,000 tokens is level with the whole conversation for all four.** Going from 1,000 to 5,000 adds 3.8 to 5.1 points.
- **LoCoMo is small, so this is an easy case.** A conversation averages about 19,400 tokens, so 5,000 tokens is about a
  quarter of it. Longer histories have not been measured at this budget.
- **The 200-memory limit trims the largest replies.** Up to 200 best-ranked memories are read, so on 454 questions the
  model reads a little under 5,000 tokens, and every needed turn is read for 89.1 % of questions against 89.5 % returned.

Reproduce with an [OpenRouter](https://openrouter.ai) key in `.env` (`OPENROUTER_API_KEY=…`). Every LLM call is
cached, and the 1,000-token run cost about $0.53; the 5,000-token runs with current models cost $1.29 to $3.99 each:

```sh
cogito-mem eval locomo-qa --data locomo10.json --env-file .env --context memory --budget 1000 --out results/locomo-qa/mem1000.json
cogito-mem eval locomo-qa --data locomo10.json --env-file .env --context memory --budget 5000 --top-k 300 --out results/locomo-qa/mem5000.json
cogito-mem eval locomo-qa --data locomo10.json --env-file .env --context full --conversations 0,1,2,3,4 --out results/locomo-qa/full.json
cogito-mem eval locomo-qa compare results/locomo-qa/full.json results/locomo-qa/mem1000.json
cogito-mem eval locomo-qa --data locomo10.json --env-file .env --protocol mem0-2026 --context memory --budget 5000 --top-k 300 --answer-model openai/gpt-5-mini --answer-reasoning low --answer-max-tokens 8000 --judge-model openai/gpt-5-mini --judge-reasoning minimal --judge-max-tokens 1500 --judges mem0-2026,mem0-2025 --out results/locomo-qa-modern/gpt-5-mini-memory5000.json
```

## LoCoMo: finding the right messages

LoCoMo labels the turns that hold each of its 1,536 answerable questions' answers. A question counts when every one of
those turns is inside the memory's reply. The baselines get the same token budget without a memory.

| What the assistant gets | 100 tokens | 300 tokens | 1,000 tokens | 2,500 tokens | 5,000 tokens |
|---|---|---|---|---|---|
| **cogito-mem** (hybrid, `top_k` 100, the API's maximum) | 39.1 % | **56.5 %** | **72.5 %** | 81.3 % | 82.5 % |
| **cogito-mem** (hybrid, `--top-k 300`, past the API's maximum) | 39.1 % | 56.6 % | 74.1 % | 82.4 % | **89.5 %** |
| cogito-mem, keyword only (`top_k` 100) | 36.0 % | 49.5 % | 59.8 % | 63.6 % | 65.0 % |
| cogito-mem, keyword only (`--top-k 300`) | 36.0 % | 49.5 % | 59.8 % | 64.1 % | 70.2 % |
| The most recent N tokens of the conversation (no memory) | 0.1 % | 0.6 % | 4.2 % | 11.1 % | 22.2 % |
| N tokens of randomly chosen turns | 0.4 % | 1.3 % | 5.1 % | 10.0 % | 19.5 % |

The random row is one draw per question and moves by a point or so with the seed; the 19 Oct run scored 0.3, 1.0 and
3.5 for the first three budgets.

**`top_k` limits the reply as well as the budget.** A LoCoMo turn averages about 28 tokens, so 100 turns hold about
2,750 tokens. With `top_k` 100, a 5,000-token budget stops there, which is why the first row barely moves after 2,500.
Reaching a real 5,000 tokens takes about 184 turns, so those runs pass the API's limit from inside the eval. The API
itself still stops at 100.

The default is `top_k` 10, and small values cut much sooner. At a 1,000-token budget on these short turns:

| `top_k` | 10 | 20 | 100 | 300 |
|---|---|---|---|---|
| Every needed turn in the reply | 63.1 % | 68.4 % | 72.5 % | 74.1 % |

The scores on this page use `top_k` 100 or more unless a row says otherwise. Going from 100 to 300 helps at 1,000 tokens
even though no reply reaches 100 turns there (+1.6 points, 0.9 to 2.3), because the search also considers more
candidates.

**What is still missing at 5,000 tokens**, by question type (`--top-k 300`):

| Category | Questions | 300 tokens | 1,000 tokens | 2,500 tokens | 5,000 tokens |
|---|---|---|---|---|---|
| single-hop | 841 | 71.1 % | 89.8 % | 95.4 % | 98.3 % |
| temporal | 321 | 68.8 % | 81.3 % | 89.7 % | 95.6 % |
| open-domain | 92 | 25.0 % | 46.7 % | 57.6 % | 68.5 % |
| multi-hop | 282 | 9.9 % | 28.0 % | 43.3 % | 63.1 % |

What it means:

- **A small budget goes far.** A conversation averages about 19,400 tokens. With 300 tokens (1.5 % of that),
  cogito-mem hands back every turn a question needs for 56.5 % of questions: single-hop 71 %, temporal 68 %,
  multi-hop 10 %. Multi-hop questions need several turns at once. A context window of the same size almost never does.
- **The gap closes slowly, and multi-hop questions are most of it.** Each step up in budget gets less: 15.4 points from
  1,000 tokens to 5,000 even though 5,000 is about a quarter of a whole conversation. Of the 161 questions still missing
  a turn at 5,000, 104 are multi-hop.
- **Meaning and words together beat words alone** by 7.0 points at 300 tokens (95 % CI 5.3 to 8.8), 12.7 at 1,000
  (11.0 to 14.5) and 19.3 at 5,000 (17.3 to 21.4).
- **Context makes the vectors useful.** Each message is embedded together with its author and the message it replies
  to. In an earlier run with a stand-in model (Qwen3-Embedding-0.6B), embedding each turn alone scored 18 points lower
  ([the ablation](requirements.md#15-choices-made-while-building-v0-author-to-confirm)).

Reproduce with `cogito-mem eval locomo --data locomo10.json`. It runs all five budgets at `top_k` 100; add
`--top-k 300` for the rows past the API's maximum and `--search keyword` for keyword only.

## Speed

1,000 queries, one at a time, `top_k` 10, a budget of 300 tokens. Every query is embedded by EmbeddingGemma 2, over a
memory of synthetic text with random vectors. The design target is a p95 under 100 ms at 10M tokens on the laptop's
CPU alone.

| Memory size | Query embedded on | Median query | p95 query |
|---|---|---|---|
| 1M tokens (10.7k items) | CPU only | 14.5 ms | 22.8 ms |
| 10M tokens (106k items) | CPU only | 17.8 ms | **26.0 ms** |
| 10M tokens (106k items) | GPU (Metal) | 13.0 ms | 14.2 ms |
| 10M tokens, `top_k` 100, a budget of 5,000 | CPU only | 20.7 ms | 29.4 ms |
| 10M tokens, `top_k` 100, a budget of 5,000 | GPU (Metal) | 14.2 ms | 15.3 ms |

Saving is fast because embedding happens in the background. Medians at 10M tokens:

| Message size | Append, CPU only | Append, Metal |
|---|---|---|
| 512 tokens | 2.2 ms | 0.8 ms |
| 4k tokens | 7.4 ms | 4.7 ms |
| 8k tokens | 10.9 ms | 9.1 ms |

A new item can be found by meaning about 57 ms after it is saved on the CPU, and 13 ms after with Metal. With Metal,
the model embeds about 21k tokens a second (1M tokens in 47 s).

**Next to published search times** (95 % of searches within). These compare designs, not hardware: hosted memories
include the network and their own AI calls.

| Memory | p95 search |
|---|---|
| **cogito-mem, 10M tokens, laptop CPU** | **26 ms** |
| Zep, its own 2026 page | 155 ms |
| Mem0, open source (Mem0 paper) | 200 ms |
| Mem0 with graph (Mem0 paper) | 657 ms |
| Mem0 platform, April 2026 run | 6.0 s |

Reproduce with `COGITO_MEM_GPU_LAYERS=0 cogito-mem bench speed --tokens 10M --random-vectors` (leave out the variable
for Metal; add `--top-k 100 --budget 5000` for the larger replies).
