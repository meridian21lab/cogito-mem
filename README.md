# cogito-mem

A fast, simple memory for agents that runs on your own machine. Agents **append** text and **query** it with one
fixed JSON shape: items go in, and items come out. The memory keeps time, never forgets (it only appends), and
returns the few stored messages that answer a question within a token budget. It is built on a frozen open
embedding model (EmbeddingGemma 2) running in llama.cpp on a CPU; a GPU only makes it faster.

```json
{ "op": "append", "namespace": "team", "items": [
  { "thread_id": "merger-x", "author": "planning-agent", "valid_at": "2026-10-14T16:00:00Z",
    "title": "Jana's report", "text": "…" } ] }
```

```json
{ "op": "query", "namespace": "team", "text": "What did Jana's report say about costs?",
  "as_of": null, "top_k": 10, "max_tokens": 300 }
```

The query returns `items`, each with `id`, `kind`, `text`, `score`, `author`, `thread_id`, `valid_at`,
`created_at` and a `source` span pointing back to the original text.

**Status:** design agreed, nothing built yet. Next is stage 0: build the untrained memory and measure it on the
long LongMemEval benchmark and on a laptop CPU.

| Document | What is in it |
|---|---|
| [`docs/requirements.md`](docs/requirements.md) | The API, the tests, the gates, the stages and the decision log. |
| [`docs/literature/memory_api_notation_and_digests.md`](docs/literature/memory_api_notation_and_digests.md) | How other memory APIs name things, fact-checkers, surprise, EmbeddingGemma, benchmarks. |
| [`docs/literature/agent_memory_systems.md`](docs/literature/agent_memory_systems.md) | A survey of agent memory systems. |
| [`docs/notes/`](docs/notes/) | Earlier design pages (17 Oct), kept as background. |
