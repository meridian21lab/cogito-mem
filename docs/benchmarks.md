# Benchmarks: how Cogi was measured, and how to reproduce it

The short version is on the [Results page](https://meridian21lab.github.io/cogito-mem/results.html).
All numbers below were measured on 19 Oct 2026 (LongMemEval-S on 20 Oct) on the author's laptop (MacBook Pro,
Apple M5 Max, 18 cores) with the model that ships, EmbeddingGemma 2 (Q8_0) in llama.cpp, and are reproducible with
the commands shown. They are internal checks, not a leaderboard entry.

**Finding the right messages (LoCoMo).** [LoCoMo](https://github.com/snap-research/locomo) holds 10 long
conversations (up to 35 sessions each) and 1,536 answerable questions whose answers are labelled with the turns
that hold them. We count a question as answered when every one of those turns is inside the memory's
reply; the baselines get the same token budget without a memory.

| What the assistant gets | Within 100 tokens | Within 300 tokens | Within 1,000 tokens |
|---|---|---|---|
| **cogito-mem** (default: hybrid search) | 39.0 % | **56.5 %** | **72.5 %** |
| cogito-mem, keyword search only | 36.0 % | 49.5 % | 59.8 % |
| The most recent N tokens of the conversation (no memory) | 0.1 % | 0.6 % | 4.2 % |
| N tokens of randomly chosen turns | 0.3 % | 1.0 % | 3.5 % |

A conversation averages about 19,400 tokens. With 300 tokens, 1.5 % of that, cogito-mem hands back every turn a
question needs for 56.5 % of the 1,536 questions (single-hop 71 %, temporal 68 %; multi-hop questions, which need
several turns at once, 10 %); a context window of the same size almost never does. Hybrid search beats
keyword search alone by 7.0 points at 300 tokens (95 % CI 5.3 to 8.8) and 12.7 points at 1,000 (11.0 to 14.5).
Embedding each message together with its author and the message it replies to is what makes the vectors useful
here: in an earlier run with a stand-in model (Qwen3-Embedding-0.6B), embedding each turn alone scored 18 points
lower ([the ablation](requirements.md#15-choices-made-while-building-v0-author-to-confirm)).

Reproduce with `cogito-mem eval locomo --data locomo10.json` (add `--search keyword` for the second row).

**Answering from the memory (LoCoMo, judged by an LLM).** This is the protocol of the
[Mem0 paper](https://arxiv.org/abs/2504.19413), which published memory systems report: gpt-4o-mini answers each
of the 1,540 questions of categories 1–4 from what the memory returns, and gpt-4o-mini then marks the answer
correct or wrong against LoCoMo's gold answer. As a check on the harness, the whole conversation is scored the
same way. One run per row.

| What gpt-4o-mini reads | All 10 conversations (1,540 questions) | First 5 conversations (762 questions) |
|---|---|---|
| cogito-mem, 300 tokens | 65.3 % | 67.8 % |
| cogito-mem, 1,000 tokens | **74.7 %** | 74.7 % |
| cogito-mem, 2,500 tokens | 76.9 % | 78.1 % |
| The whole conversation (no memory) | not run | 76.5 % |

On the same 762 questions, 1,000 tokens from cogito-mem is level with the whole conversation (−1.8 points, 95 % CI
−5.5 to +1.8); 300 tokens is 8.7 points below it (−12.5 to −4.7). Under the same protocol the Mem0 paper reports
66.9 for Mem0, 68.4 for Mem0g and 66.0 for Zep (as Mem0 ran it) against 72.9 for the whole conversation, 3.6
points below our own full-context run, so absolute scores from different harnesses are not directly comparable.
Reproduce with an [OpenRouter](https://openrouter.ai) key in `.env` (`OPENROUTER_API_KEY=…`); every LLM call is
cached, and the 1,000-token run cost about $0.53:

```sh
cogito-mem eval locomo-qa --data locomo10.json --env-file .env --context memory --budget 1000 --out results/locomo-qa/mem1000.json
cogito-mem eval locomo-qa --data locomo10.json --env-file .env --context full --conversations 0,1,2,3,4 --out results/locomo-qa/full.json
cogito-mem eval locomo-qa compare results/locomo-qa/full.json results/locomo-qa/mem1000.json
```

**Speed** (`cogito-mem bench speed`, 1,000 queries, one at a time, `top_k` 10, budget 300 tokens; every query is
embedded by EmbeddingGemma 2, over a memory of synthetic text with random vectors):

| Memory size | Query embedded on | Median query | p95 query |
|---|---|---|---|
| 1M tokens (10.7k items) | CPU only | 14.5 ms | 22.8 ms |
| 10M tokens (106k items) | CPU only | 17.8 ms | **26.0 ms** |
| 10M tokens (106k items) | GPU (Metal) | 13.0 ms | 14.2 ms |

The design target is a p95 under 100 ms at 10M tokens on the author's laptop with the CPU alone; measured there,
it is 26 ms. Appending is fast because embedding happens in the background: at 10M tokens on the CPU, a median of
2.2 ms for a 512-token message, 7.4 ms for 4k tokens and 10.9 ms for 8k tokens (0.8, 4.7 and 9.1 ms with Metal); a
new item can be found by meaning about 57 ms later on the CPU and 13 ms later with Metal. With Metal, the model
embeds about 21k tokens a second (1M tokens in 47 s). Reproduce with
`COGITO_MEM_GPU_LAYERS=0 cogito-mem bench speed --tokens 10M --random-vectors` (leave out the variable for Metal).

**Finding the right session (LongMemEval-S).** [LongMemEval](https://github.com/xiaowu0162/LongMemEval) gives each
of its 500 questions a history of about 50 chat sessions (about 115k tokens) and labels the sessions, and the turns
in them, that hold the answer. The number other local memory tools publish for it is session-level recall at 5, with
no LLM involved: the share of questions for which a session holding the answer is among the first five sessions
found. `eval longmemeval-recall` loads each question's sessions into a fresh memory (one item per turn, dated by its
session), asks the question, and reports that recall at 1, 3, 5 and 10, the stricter variant (every answer session
in the top k, "all@k"), NDCG@10, MRR and turn-level recall, overall and per question type. It counts all 500
questions, as deja-vu and MemPalace do, and separately the 470 that are not abstention questions, as LongMemEval's
own retrieval evaluation does.

It can ask in two ways. With `--as-of none`, every session in the history can be found: this is LongMemEval's own
retrieval protocol, and the one behind deja-vu's 97.2 and MemPalace's 96.6. By default, it asks as of the question's
date, as the memory is asked in use, so a session dated after the question stays hidden. That is stricter, because
44 of the 500 questions have an answer session dated later than the question (always later the same day), and for
20 of them every answer session is. Measured on 20 Oct 2026 on the same laptop and model, with Metal, session level,
all 500 questions:

| Search | Sessions it can find | R@1 | R@3 | **R@5** | R@10 | all@5 | NDCG@10 | MRR |
|---|---|---|---|---|---|---|---|---|
| **cogito-mem** (default: hybrid search) | all (`--as-of none`) | 92.6 | 98.0 | **99.0** | 99.4 | 90.8 | 0.946 | 0.953 |
| **cogito-mem** (default: hybrid search) | up to the question date | 88.8 | 94.0 | **95.0** | 95.4 | 83.0 | 0.890 | 0.914 |
| cogito-mem, keyword search only | all (`--as-of none`) | 85.2 | 93.0 | **95.0** | 98.0 | 80.6 | 0.880 | 0.898 |
| cogito-mem, keyword search only | up to the question date | 81.4 | 88.8 | **91.0** | 94.0 | 73.8 | 0.827 | 0.858 |

Under LongMemEval's protocol, an answer session is among the first five found for 99.0 % of the questions, including
all 30 abstention questions; deja-vu and MemPalace report 97.2 and 96.6 from their own harnesses. As of the question
date it is 95.0 %, and the gap is the late sessions: of the 23 questions hybrid search misses even in the top 10, 20
have every answer session dated after the question, where the cutoff hides them as it should. 43 of the 44
questions with a late session are temporal-reasoning questions, and that type's R@5 is 83.5 as of the question date
and 97.6 with no cutoff. As of the question date, hybrid search is ahead of keyword search alone by 4.0 points of R@5
(95 % CI 2.2 to 5.8), 9.2 points of all@5 (6.6 to 11.8) and 6.3 points of NDCG@10 (4.7 to 7.9), paired over the
same questions. A query takes a median of 11 ms as of the question date and 19 ms with no cutoff; loading a
question's history takes 4.7 s with an empty embedding cache, so a first hybrid run takes about 40 minutes and a
rerun about 3. Download `longmemeval_s_cleaned.json` from
[the dataset page](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned), then:

```sh
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --out results/lme-recall/hybrid.json --questions-out results/lme-recall/hybrid.jsonl
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --as-of none --out results/lme-recall/hybrid-no-cutoff.json
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --search keyword --out results/lme-recall/keyword.json
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --search keyword --as-of none --out results/lme-recall/keyword-no-cutoff.json
cogito-mem eval longmemeval-recall compare results/lme-recall/keyword.json results/lme-recall/hybrid.json
```

Rerunning with the same `--questions-out` file resumes an interrupted run, and embeddings are cached.
