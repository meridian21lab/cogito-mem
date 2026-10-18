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
`created_at`, `expired_at` and a `source` span pointing back to the original text.

**Status:** v0 is built and tested (see [Testing](#testing)). Next is stage 0: measure the untrained memory on the
long LongMemEval benchmark and on a laptop CPU with the tools in [Measuring](#measuring-stage-0).

## Install

One command connects the memory to a chat client. Nothing to configure: no account, no API key, no config file.

```sh
uvx --from git+https://github.com/meridian21lab/cogito-mem cogito-mem install claude-code   # or: codex, claude-desktop
```

(or `pip install git+https://github.com/meridian21lab/cogito-mem` and then `cogito-mem install claude-code`).

It:
- creates the memory folder `~/.cogito-mem/` with the namespace `default`;
- gets llama.cpp's `llama-server` (uses the one on your `PATH`, e.g. from `brew install llama.cpp`, or downloads
  the prebuilt release) and the EmbeddingGemma 2 GGUF (`ggml-org/embeddinggemma-2-GGUF`, Q8_0, 310 MB);
- registers the MCP server with the client (local, over stdio);
- turns on automatic capture: Claude Code `Stop`/`SessionEnd` hooks, Codex `notify`;
- starts the local service and checks it answers.

`cogito-mem uninstall <client>` removes only what install added. The memory itself stays in `~/.cogito-mem/`.
Config files are backed up once (`*.cogito-mem.bak`) before they are first changed.

Without llama.cpp or the model the memory still works, by keyword search; `cogito-mem status` says which.

## Use

**From a chat.** The assistant gets two MCP tools, `memory_append` (`text`, optional `title`) and `memory_query`
(`text`, optional `valid_after`, `valid_before`, `max_tokens`). The server's instructions tell it to search when
you refer to earlier work ("do you remember that idea from a week ago?") and to save ideas, decisions, open
questions and facts you state. Claude Code and Codex chats are also captured as you go.

**Past chats** from claude.ai and ChatGPT come in from the apps' data exports:

```sh
cogito-mem import claude  ~/Downloads/data-2026-10-18.zip
cogito-mem import chatgpt ~/Downloads/chatgpt-export.zip
cogito-mem capture claude-code --all     # backfill earlier Claude Code sessions
cogito-mem capture codex --all           # backfill earlier Codex sessions
```

**From the command line or any program:**

```sh
cogito-mem append "Decision: v0 ships with keyword search on by default." --title release
cogito-mem query "what did we decide about keyword search?"
curl -s localhost:7327/v1/memory -H 'Content-Type: application/json' \
     -d '{"op": "query", "text": "keyword search decision"}'
```

**From Python**, with the same dictionaries:

```python
from cogito_mem import Memory, Client

mem = Memory()                     # in this process, on ~/.cogito-mem
mem.handle({"op": "append", "items": [{"author": "user", "text": "The mascot is a squirrel called Cogi."}]})
mem.handle({"op": "query", "text": "what is the mascot called?"})

Client().query("mascot")           # or through the local service, started on demand
```

## How it works

```
 Claude Code ─ hooks ──┐                       ┌─ log.sqlite3 per namespace (append-only, the source of truth)
 Codex ─ notify ───────┤                       ├─ BM25 keyword index (in memory, rebuilt from the log)
 MCP clients ─ stdio ──┼─ POST /v1/memory ──▶ service ─┼─ vectors: 256 numbers, 16 bits (in memory + shared cache)
 CLI, Python, curl ────┘   127.0.0.1:7327      └─ llama-server: EmbeddingGemma 2 (tokenizer + embeddings)
```

- **One warm service** (`cogito-mem serve`) holds the memory and the model. The MCP server, the hooks and the CLI
  are thin clients that start it on demand; it stops after an hour idle. It listens on 127.0.0.1 only and refuses
  non-JSON bodies and foreign `Host` headers, so a web page cannot read or write it.
- **Append:** the text is split into pieces of at most 256 tokens (at paragraph breaks, then sentence breaks),
  written to the log and the keyword index, and the call returns. Embedding happens in the background with the
  document prompt `title: {title|none} | text: {text}`; vectors are cut to 256 numbers, normalised and stored in
  16 bits in a content-addressed cache, so text seen twice is embedded once.
- **Query:** embed `task: search result | query: {text}`, mask the items by `as_of` and the filters, run an exact
  cosine search and BM25, fuse them by reciprocal rank, and fill items in score order up to `top_k` and
  `max_tokens` (counted with the EmbeddingGemma 2 tokenizer). An optional reranker reorders the top 30.
- **Time:** `created_at` is set by the memory (strictly increasing); `valid_at` comes from the caller; `as_of`
  views the memory as it stood at any moment, retractions included.

The full specification, the tests and the decision log are in [`docs/requirements.md`](docs/requirements.md).

## Measuring (stage 0)

```sh
# quality: coverage at N tokens on LongMemEval (one run per arm), then the paired comparison
cogito-mem eval run --data longmemeval_m.json --arm U1 --out results/u1.json
cogito-mem eval run --data longmemeval_m.json --arm U2 --out results/u2.json --build-check 0.60,0.72
cogito-mem eval run --data longmemeval_m.json --arm U3 --base U2 --out results/u3.json
cogito-mem eval run --data longmemeval_m.json --arm R --reranker qwen3-reranker-0.6b.gguf --out results/r.json
cogito-mem eval compare results/u2.json results/r.json --budget 300

# speed: p95 query time at 10M tokens, CPU only
COGITO_MEM_GPU_LAYERS=0 cogito-mem bench speed --data longmemeval_m.json --tokens 10M --out results/speed.json
```

Every result records the dataset hash, the GGUF file and quantization, the commit, the machine and the time.
Embedding 10M tokens on a laptop CPU takes hours: fill the cache on a GPU machine with `bench speed --embed-only`
and copy `~/.cogito-mem/cache/embeddings.sqlite3` over (the `--build-check` values above are placeholders: write
the paper's row into `docs/requirements.md` first).

## Settings

Everything has a working default. Environment variables, for when you need them:

| Variable | Meaning |
|---|---|
| `COGITO_MEM_HOME` | The memory folder (default `~/.cogito-mem`). |
| `COGITO_MEM_PORT` | The service port (default 7327). |
| `COGITO_MEM_MODEL` / `COGITO_MEM_MODEL_URL` | A local GGUF to use, or where to download it from. |
| `COGITO_MEM_LLAMA_SERVER` | A `llama-server` binary, or the URL of a running one. |
| `COGITO_MEM_GPU_LAYERS` / `COGITO_MEM_THREADS` | Passed to llama.cpp as `-ngl` / `-t` (`0` layers = CPU only). |
| `COGITO_MEM_RERANKER` | A reranker GGUF or llama-server URL (stage-0 arm R). |
| `COGITO_MEM_NO_DOWNLOAD` | Never download anything. |

## Testing

```sh
pip install -e '.[test]'
pytest                                   # 117 tests; the llama.cpp ones are skipped without a model
COGITO_MEM_TEST_LLAMA_SERVER=$(which llama-server) \
COGITO_MEM_TEST_MODEL=~/.cogito-mem/models/embeddinggemma-2-Q8_0.gguf pytest
```

Without the real model, `scripts/make_tiny_embeddinggemma2.py --llama-cpp <checkout> --out tiny.gguf` writes a
50 MB random-weight model of the same architecture with the real tokenizer, which is enough to test the plumbing.
CI builds llama.cpp and runs the suite with it.

The suite covers the API contract (static keys, defaults, errors, `as_of`, retraction, filters, the fill rule,
pieces and spans), storage across processes, the HTTP service, the MCP server (also against the official MCP
Python SDK client), capture from each client, install and uninstall, the stage-0 tools, and both acceptance tests
of §3.5 end to end: setup in one command, and finding "that idea from a week ago" with one `memory_query`.

## Documents

| Document | What is in it |
|---|---|
| [`docs/requirements.md`](docs/requirements.md) | The API, the tests, the gates, the stages and the decision log. |
| [`docs/literature/memory_api_notation_and_digests.md`](docs/literature/memory_api_notation_and_digests.md) | How other memory APIs name things, fact-checkers, surprise, EmbeddingGemma, benchmarks. |
| [`docs/literature/agent_memory_systems.md`](docs/literature/agent_memory_systems.md) | A survey of agent memory systems. |
| [`docs/notes/`](docs/notes/) | Earlier design pages (17 Oct), kept as background. |
