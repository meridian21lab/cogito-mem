# Benchmarks: how Cogi was measured, and how to reproduce it

The short version is on the [Results page](https://meridian21lab.github.io/cogito-mem/results.html).
All numbers below were measured on 19 Oct 2026 on the author's laptop (MacBook Pro, Apple M5 Max, 18 cores) with
the model that ships, EmbeddingGemma 2 (Q8_0) in llama.cpp, and are reproducible with the commands shown. They are
internal checks, not a leaderboard entry.

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

**Finding the right session (LongMemEval-S).** To be measured. [LongMemEval](https://github.com/xiaowu0162/LongMemEval)
gives each of its 500 questions a history of about 50 chat sessions (about 115k tokens) and labels the sessions, and
the turns in them, that hold the answer. The number other local memory tools publish for it is session-level recall
at 5, with no LLM involved: the share of questions for which a session holding the answer is among the first five
sessions found. `eval longmemeval-recall` loads each question's sessions into a fresh memory (one item per turn,
dated by its session), asks the question as of the question's date, and reports that recall at 1, 3, 5 and 10, the
stricter variant (every answer session in the top k), NDCG@10 and turn-level recall, overall and per question type.
It counts all 500 questions, as deja-vu and MemPalace do, and separately the 470 that are not abstention questions,
as LongMemEval's own retrieval evaluation does. Download `longmemeval_s_cleaned.json` from
[the dataset page](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned), then:

```sh
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --out results/lme-recall/hybrid.json --questions-out results/lme-recall/hybrid.jsonl
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --search keyword --out results/lme-recall/keyword.json
cogito-mem eval longmemeval-recall compare results/lme-recall/keyword.json results/lme-recall/hybrid.json
```

Rerunning with the same `--questions-out` file resumes an interrupted run, and embeddings are cached.
