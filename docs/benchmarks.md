# Benchmarks: how Cogi was measured, and how to reproduce it

The short version, with charts, is on the [Results page](https://meridian21lab.github.io/cogito-mem/results.html).
This page has every number, how it was measured and the commands to reproduce it. Everything was measured on the
author's laptop (MacBook Pro, Apple M5 Max, 18 cores) with the model that ships, EmbeddingGemma 2 (Q8_0) in
llama.cpp: LoCoMo and speed on 19 Oct 2026, LongMemEval-S on 20 Oct 2026. These are our own runs, not leaderboard
entries.

- [At a glance](#at-a-glance)
- [LongMemEval-S: finding the right session](#longmemeval-s-finding-the-right-session)
- [LoCoMo: answering from the memory](#locomo-answering-from-the-memory)
- [LoCoMo: finding the right messages](#locomo-finding-the-right-messages)
- [Speed](#speed)

## At a glance

| Test | What it measures | cogito-mem | Next to |
|---|---|---|---|
| LongMemEval-S, 500 questions | a session holding the answer is among the first 5 found; no LLM | **99.0 %** (95.0 % as of the question date) | other local memory plugins publish 95.2–98.0 % |
| LoCoMo, 1,540 questions | gpt-4o-mini answers from 1,000 tokens of memory, gpt-4o-mini grades | **74.7 %**, 98 % of the whole-conversation score | Mem0 92 %, Mem0g 94 %, Zep 91 % of theirs (Mem0 paper) |
| LoCoMo, 1,536 questions | every turn an answer needs is in 1,000 tokens of memory | **72.5 %** | the last 1,000 tokens of the conversation: 4.2 % |
| Speed, 10M tokens | 95 % of searches finish within, laptop CPU only | **26 ms** | design target: 100 ms |

**Terms.** *R@k* (recall at k): the share of questions for which at least one session holding the answer is among the
first k found. *all@k*: every such session is. *NDCG@10*: how well the first 10 are ordered, from 0 to 1 (1: every
answer session first). *MRR*: 1 ÷ the rank of the first answer session, averaged. *p95*: 95 % of searches finish
within this time. *95 % CI*: the 95 % confidence interval (Wilson for a single score, paired bootstrap for a
difference).

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

With 500 questions, hippo-memory's 98.0 lies inside cogito-mem's 95 % interval and deja-vu's 97.2 just below it. The
honest reading: level with the best two, ahead of the rest.

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
| The whole conversation (no memory) | not run | 76.5 % |

What it means:

- **1,000 tokens is level with the whole conversation.** On the same 762 questions the difference is −1.8 points
  (95 % CI −5.5 to +1.8). 300 tokens is 8.7 points below it (−12.5 to −4.7).
- **Next to the Mem0 paper.** Under the same protocol it reports 66.9 for Mem0, 68.4 for Mem0g and 66.0 for Zep (as
  Mem0 ran it), against 72.9 for the whole conversation. That is 3.6 points below our own whole-conversation run, so
  absolute scores from different harnesses are not directly comparable. The Results page therefore shows each score
  as a share of its own harness's whole-conversation score.

Reproduce with an [OpenRouter](https://openrouter.ai) key in `.env` (`OPENROUTER_API_KEY=…`). Every LLM call is
cached, and the 1,000-token run cost about $0.53:

```sh
cogito-mem eval locomo-qa --data locomo10.json --env-file .env --context memory --budget 1000 --out results/locomo-qa/mem1000.json
cogito-mem eval locomo-qa --data locomo10.json --env-file .env --context full --conversations 0,1,2,3,4 --out results/locomo-qa/full.json
cogito-mem eval locomo-qa compare results/locomo-qa/full.json results/locomo-qa/mem1000.json
```

## LoCoMo: finding the right messages

LoCoMo labels the turns that hold each of its 1,536 answerable questions' answers. A question counts when every one of
those turns is inside the memory's reply. The baselines get the same token budget without a memory.

| What the assistant gets | Within 100 tokens | Within 300 tokens | Within 1,000 tokens |
|---|---|---|---|
| **cogito-mem** (default: hybrid) | 39.0 % | **56.5 %** | **72.5 %** |
| cogito-mem, keyword only | 36.0 % | 49.5 % | 59.8 % |
| The most recent N tokens of the conversation (no memory) | 0.1 % | 0.6 % | 4.2 % |
| N tokens of randomly chosen turns | 0.3 % | 1.0 % | 3.5 % |

What it means:

- **A small budget goes far.** A conversation averages about 19,400 tokens. With 300 tokens (1.5 % of that),
  cogito-mem hands back every turn a question needs for 56.5 % of questions: single-hop 71 %, temporal 68 %,
  multi-hop 10 %. Multi-hop questions need several turns at once. A context window of the same size almost never does.
- **Meaning and words together beat words alone** by 7.0 points at 300 tokens (95 % CI 5.3 to 8.8) and 12.7 at 1,000
  (11.0 to 14.5).
- **Context makes the vectors useful.** Each message is embedded together with its author and the message it replies
  to. In an earlier run with a stand-in model (Qwen3-Embedding-0.6B), embedding each turn alone scored 18 points lower
  ([the ablation](requirements.md#15-choices-made-while-building-v0-author-to-confirm)).

Reproduce with `cogito-mem eval locomo --data locomo10.json` (add `--search keyword` for the second row).

## Speed

1,000 queries, one at a time, `top_k` 10, a budget of 300 tokens. Every query is embedded by EmbeddingGemma 2, over a
memory of synthetic text with random vectors. The design target is a p95 under 100 ms at 10M tokens on the laptop's
CPU alone.

| Memory size | Query embedded on | Median query | p95 query |
|---|---|---|---|
| 1M tokens (10.7k items) | CPU only | 14.5 ms | 22.8 ms |
| 10M tokens (106k items) | CPU only | 17.8 ms | **26.0 ms** |
| 10M tokens (106k items) | GPU (Metal) | 13.0 ms | 14.2 ms |

Saving is fast because embedding happens in the background. Medians at 10M tokens:

| Message size | Append, CPU only | Append, Metal |
|---|---|---|
| 512 tokens | 2.2 ms | 0.8 ms |
| 4k tokens | 7.4 ms | 4.7 ms |
| 8k tokens | 10.9 ms | 9.1 ms |

A new item can be found by meaning about 57 ms after it is saved on the CPU, and 13 ms after with Metal. With Metal,
the model embeds about 21k tokens a second (1M tokens in 47 s).

Reproduce with `COGITO_MEM_GPU_LAYERS=0 cogito-mem bench speed --tokens 10M --random-vectors` (leave out the variable
for Metal).
