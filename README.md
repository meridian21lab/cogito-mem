# cogito-mem

**Long-term memory for your AI assistants, on your own machine.**

🐿️ **Docs: [meridian21lab.github.io/cogito-mem](https://meridian21lab.github.io/cogito-mem/)**: install in two minutes, how it works, results, API and MCP.

[![tests](https://github.com/meridian21lab/cogito-mem/actions/workflows/tests.yml/badge.svg)](https://github.com/meridian21lab/cogito-mem/actions/workflows/tests.yml)
[![docker](https://github.com/meridian21lab/cogito-mem/actions/workflows/docker.yml/badge.svg)](https://github.com/meridian21lab/cogito-mem/actions/workflows/docker.yml)
![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue)

Claude Code, Codex and Claude Desktop forget everything when a session ends. The idea you had last Tuesday, the
reason you chose SQLite, the bug you half-fixed: gone, unless somebody wrote it down.

cogito-mem writes it down for you. It captures your sessions as you work and gives your assistant two tools,
*save* and *recall*, so a week later this works:

> **You:** Do you remember that idea from a week ago? I'd like to revisit it.
> **Claude:** *(one `memory_query`)* Yes. On Oct 11 you said: "agents could subscribe to a thread and get new
> items pushed to them instead of polling." You were fixing the date parser at the time.

Everything stays in a folder on your computer. No account, no API key, no cloud.

In Claude Code, with [uv](https://docs.astral.sh/uv/) installed, two commands in a terminal:

```sh
claude plugin marketplace add meridian21lab/cogito-mem
claude plugin install cogito-mem@cogito-mem --scope user
```

That's the whole setup ([the install guide](https://meridian21lab.github.io/cogito-mem/start.html) shows what you should
see at each step). For Codex and Claude Desktop as well, one line connects every client it finds:

```sh
curl -fsSL https://raw.githubusercontent.com/meridian21lab/cogito-mem/main/install.sh | sh
```

> **Early access.** v0.1 is new. It is built and tested (132 tests, including both end-to-end acceptance tests),
> and we are measuring it before calling it stable. Feedback and issues are very welcome.

## What you get

- **It remembers every session by itself.** Claude Code and Codex conversations are captured after each turn.
  Past chats from claude.ai and ChatGPT come in from their data exports.
- **It finds things by meaning and by words.** An open embedding model (Google's EmbeddingGemma 2) runs locally in
  llama.cpp, next to classic keyword search; the two rankings are fused.
- **It answers in a few tokens.** A query returns the handful of stored messages that answer it, word for word,
  within a token budget you set (1,000 by default), each pointing back to the original message.
- **It knows when.** Every item records when it was said and when it was stored. Ask about "a week ago", or view
  the memory as it stood on any past date.
- **It never forgets and never invents.** The log is append-only: a correction is a new item that withdraws an
  old one. Nothing is generated at query time; you only ever get back what was stored.
- **It stays private.** One folder on your disk, a service that listens on `127.0.0.1` only and refuses browser
  requests, and API keys or passwords in captured chats are replaced with `[redacted]`.
- **It is shared by all your assistants.** Claude Code, Codex, Claude Desktop, any MCP client, your scripts (HTTP
  and Python) read and write the same memory.
- **It needs no setup.** One command. `cogito-mem doctor` explains anything that is missing.

## How it is different

| | cogito-mem | Notes files (`CLAUDE.md`, `AGENTS.md`) | Memory services that extract facts with an LLM |
|---|---|---|---|
| What gets stored | every message, automatically | what you or the agent write down | facts an LLM decides to keep |
| What comes back | the original words, with a pointer to where they came from | the whole file, every session | rewritten facts |
| Cost of storing | a local embedding, no API calls | none | an LLM call per write |
| Time | when it was said, when it was stored, "as of" any date | none | varies |
| Where it lives | a folder on your machine | your repository | usually a hosted service |

They work well together: keep the rules for your project in `CLAUDE.md`, and let cogito-mem remember what
happened.

## Measured

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
lower ([the ablation](docs/requirements.md#15-choices-made-while-building-v0-author-to-confirm)).

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

## Use it

**In a chat.** Your assistant decides when to use the two tools; you can also ask directly:

- *"Remember that we ship the beta to ten design partners first."* → `memory_append`
- *"What did we decide about the beta?"*, *"What was that idea from last week?"* → `memory_query`

**Without asking, in Claude Code.** Each prompt is looked up before Claude sees it, and up to 300 tokens of what
earlier sessions said about it come along: items from the current project first, each with its date and author,
nothing from the session you are in, and nothing at all when no match is strong enough. A new session also starts
with how the last session in the same project ended. Recall never holds up a prompt by more than about a second.
To turn it off, set `COGITO_MEM_RECALL=off` (for example under `"env"` in `~/.claude/settings.json`, which also
works for the plugin) or run `cogito-mem install claude-code --no-recall`; `COGITO_MEM_RECALL_MIN_SCORE` (default
0.6) sets how strong a match must be.

**From a terminal:**

```sh
cogito-mem query "beta design partners"
cogito-mem append "Decision: v0 keeps keyword search on by default." --title release
cogito-mem import claude ~/Downloads/data-2026-10-18.zip     # or: import chatgpt …
cogito-mem capture claude-code --all                         # bring in every earlier session
cogito-mem doctor                                            # check the install
```

**Over HTTP** (`POST /v1/memory`, one JSON shape for everything):

```sh
curl -s localhost:7327/v1/memory -H 'Content-Type: application/json' \
  -d '{"op": "append", "items": [{"author": "planner", "thread_id": "merger-x", "text": "Integration costs are 40 % above plan."}]}'
curl -s localhost:7327/v1/memory -H 'Content-Type: application/json' \
  -d '{"op": "query", "text": "What did we learn about costs?", "max_tokens": 300}'
```

Each returned item carries `id`, `kind`, `text`, `score` (a rank within the response), `similarity` (the cosine
between query and item vectors, `null` without them), `author`, `thread_id`, `valid_at`, `created_at`,
`expired_at` and a `source` span (`id`, `title`, `start`, `end`) into the original message. The full API, with
`as_of`, filters, imports and retractions, is in [`docs/requirements.md`](docs/requirements.md#3-api-v0).

**From Python**, with the same dictionaries:

```python
from cogito_mem import Memory, Client

mem = Memory()                    # in this process, on ~/.cogito-mem
mem.handle({"op": "append", "items": [{"author": "user", "text": "The mascot is a squirrel called Cogi."}]})
mem.handle({"op": "query", "text": "what is the mascot called?"})

Client().query("mascot")          # or through the local service, which starts on demand
```

**From any MCP client**, over stdio (`cogito-mem mcp`) or by URL: `http://127.0.0.1:7327/mcp`.

## Install and deploy

| Way | Command | Notes |
|---|---|---|
| One line | `curl -fsSL https://raw.githubusercontent.com/meridian21lab/cogito-mem/main/install.sh \| sh` | Needs only curl; connects every client it finds. Windows: `install.ps1` (experimental). |
| Claude Code plugin | `claude plugin marketplace add meridian21lab/cogito-mem` then `claude plugin install cogito-mem@cogito-mem --scope user` (or `/plugin …` inside Claude Code) | MCP server, capture and recall hooks; `--config memory_name=…` names your memory. |
| Docker | `docker run -d -p 127.0.0.1:7327:7327 -v cogito-mem:/data ghcr.io/meridian21lab/cogito-mem`, then `claude mcp add --transport http cogito-mem http://127.0.0.1:7327/mcp` | Service, llama.cpp and model in one container (amd64 and arm64); data in a volume. |
| pip / uv | `uv tool install git+https://github.com/meridian21lab/cogito-mem && cogito-mem install` | For Python developers. |

The [install guide](docs/install.md) covers each way, upgrades, uninstalling and troubleshooting.

## How it works

```
 Claude Code ─ hooks ──┐                         ┌─ log.sqlite3 per memory: append-only, the source of truth
 Codex ─ notify ───────┤                         ├─ keyword index (BM25), in memory, rebuilt from the log
 MCP clients ─ stdio ──┼─ POST /v1/memory ─▶ service ─┼─ vectors: 256 numbers in 16 bits, in memory + a shared cache
 HTTP, Python, CLI ────┘   /mcp, 127.0.0.1:7327  └─ llama-server: EmbeddingGemma 2 (tokenizer + embeddings)
```

- **One warm service** holds the memory and the model. The MCP server, the hooks and the CLI are thin clients that
  start it when needed; it stops after an idle hour.
- **Append:** long texts are split into pieces of at most 256 tokens at paragraph, then sentence, breaks; the text
  goes to the log and the keyword index and the call returns. Embedding follows in the background.
- **Query:** the question is embedded, the memory is masked to what was known `as_of` the moment you ask about and
  to your filters, exact cosine search and BM25 are fused by reciprocal rank, and items are filled in score order
  up to `top_k` and the token budget.

## Settings

Everything has a working default. Environment variables, for when you need them:

| Variable | Meaning |
|---|---|
| `COGITO_MEM_HOME` | The memory folder (default `~/.cogito-mem`). |
| `COGITO_MEM_NAMESPACE` | The memory's name (default `<username>-hollow`, e.g. `ksirg-hollow`: Cogi's hollow, where it keeps its nuts). Saved in `~/.cogito-mem/config.json`, so every client uses it; `--namespace` picks another memory for one command. |
| `COGITO_MEM_PORT` | The service port (default 7327). |
| `COGITO_MEM_URL` | Use the service at this URL (e.g. a Docker container). |
| `COGITO_MEM_MODEL` / `COGITO_MEM_MODEL_URL` | A local GGUF to use, or where to download it from. Other Matryoshka GGUFs (Qwen3-Embedding, nomic-embed-text) get their own prompts automatically. |
| `COGITO_MEM_LLAMA_SERVER` | A `llama-server` binary, or the URL of a running one. |
| `COGITO_MEM_GPU_LAYERS` / `COGITO_MEM_THREADS` | Passed to llama.cpp as `-ngl` / `-t` (`0` layers = CPU only). |
| `COGITO_MEM_ALLOWED_HOSTS` | Extra `Host` names the service accepts (e.g. a Docker network name). |
| `COGITO_MEM_RERANKER` | A reranker GGUF or llama-server URL (reorders the top 30; GPU recommended). |
| `COGITO_MEM_NO_DOWNLOAD` | Never download anything. |

## Privacy and security

- The memory is a folder (`~/.cogito-mem/memory/<name>/log.sqlite3`). Back it up by copying it; erase it by
  deleting it.
- The service listens on `127.0.0.1` only. It refuses requests whose `Host` or `Origin` is not local and bodies
  that are not JSON, so a web page you visit can neither read nor write it. There are no accounts: anything that
  runs as you on your machine can use it, as with any local tool.
- Capture skips tool output, thinking and system text, and replaces API keys, tokens, private keys and
  `password=…` values with `[redacted]` before anything is stored.
- Nothing leaves your machine. The only network traffic is the one-time download of llama.cpp and the model.

## FAQ

**Does it work without a GPU?** Yes; it is built for a laptop CPU. A GPU (Apple Metal, NVIDIA CUDA) makes the
embedding faster.

**Which model does it use?** [EmbeddingGemma 2](https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2) (Apache 2.0),
the `ggml-org/embeddinggemma-2-GGUF` Q8_0 file (310 MB), in [llama.cpp](https://github.com/ggml-org/llama.cpp).

**How much disk does it use?** About 1 GB for llama.cpp and the model, plus roughly the size of your text again
for the memory itself.

**Can I delete something?** Append a retraction (an item whose `retracts` lists the ids): it disappears from
queries from that moment on, and stays visible to `as_of` queries about earlier times. To erase for real, delete
the memory folder.

**Does it work with claude.ai or ChatGPT in the browser?** Not live yet: those apps can only reach remote MCP
servers. Import their data exports instead (`cogito-mem import …`).

**Windows?** Experimental: the installer and the code paths exist but are not tested in CI yet.

## Roadmap

- **v0 (now):** store and retrieve messages; MCP; capture; one-command setup.
- **Stage 0:** measure the shipped model on the long LongMemEval and on the target laptop
  (`cogito-mem eval`, `cogito-mem bench`); decide whether a small trained reranking head is worth it.
- **v1:** digests: for a long text, keep its main points and its surprising facts, word for word.
- **v2:** short checked statements written by a small model, for agent-to-agent use.
- **Later:** images and files from chats; sync between machines; a remote endpoint for web clients.

The full plan, the tests that gate each step and the decision log are in
[`docs/requirements.md`](docs/requirements.md).

## Development

```sh
pip install -e '.[test]'
pytest                                   # the llama.cpp tests are skipped without a model
COGITO_MEM_TEST_LLAMA_SERVER=$(which llama-server) \
COGITO_MEM_TEST_MODEL=~/.cogito-mem/models/embeddinggemma-2-Q8_0.gguf pytest
```

`scripts/make_tiny_embeddinggemma2.py` writes a 50 MB random-weight model of the same architecture with the real
tokenizer, enough to test the llama.cpp path without downloading the model; CI builds llama.cpp and does that.
The stage-0 measurements:

```sh
cogito-mem eval locomo --data locomo10.json --search hybrid --out results/locomo.json
cogito-mem eval run --data longmemeval_m.json --arm U2 --out results/u2.json      # LongMemEval, arms U1-U3, R
cogito-mem eval compare results/u1.json results/u2.json --budget 300
COGITO_MEM_GPU_LAYERS=0 cogito-mem bench speed --data longmemeval_m.json --tokens 10M --out results/speed.json
```

| Document | What is in it |
|---|---|
| [`docs/install.md`](docs/install.md) | Every way to install, upgrade, remove and troubleshoot. |
| [`docs/requirements.md`](docs/requirements.md) | The API, the tests, the gates, the stages and the decision log. |
| [`docs/literature/`](docs/literature/) | How other memory systems work and name things; benchmarks. |

## License

MIT. The EmbeddingGemma 2 model is Apache 2.0; llama.cpp is MIT.
