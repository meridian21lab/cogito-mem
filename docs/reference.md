# Reference: using cogito-mem, settings, privacy, FAQ

The friendly version is on the [docs site](https://meridian21lab.github.io/cogito-mem/). This page has the details.

- [Use it](#use-it)
- [How it works](#how-it-works)
- [Settings](#settings)
- [Privacy and security](#privacy-and-security)
- [FAQ](#faq)
- [Roadmap](#roadmap)

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
`as_of`, filters, imports and retractions, is in [`docs/requirements.md`](requirements.md#3-api-v0).

**From Python**, with the same dictionaries:

```python
from cogito_mem import Memory, Client

mem = Memory()                    # in this process, on ~/.cogito-mem
mem.handle({"op": "append", "items": [{"author": "user", "text": "The mascot is a squirrel called Cogi."}]})
mem.handle({"op": "query", "text": "what is the mascot called?"})

Client().query("mascot")          # or through the local service, which starts on demand
```

**From any MCP client**, over stdio (`cogito-mem mcp`) or by URL: `http://127.0.0.1:7327/mcp`.

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
| `COGITO_MEM_CAPTURE` | `off` pauses capture: the hooks store nothing (`capture … --all` still runs when you ask). |
| `COGITO_MEM_CAPTURE_ACTIONS` | `off` stops the note of each Claude Code turn's commands and files (default on). |
| `COGITO_MEM_NO_DOWNLOAD` | Never download anything. |

## Privacy and security

- The memory is a folder (`~/.cogito-mem/memory/<name>/log.sqlite3`). Back it up by copying it; erase it by
  deleting it.
- The service listens on `127.0.0.1` only. It refuses requests whose `Host` or `Origin` is not local and bodies
  that are not JSON, so a web page you visit can neither read nor write it. There are no accounts: anything that
  runs as you on your machine can use it, as with any local tool.
- Capture skips tool output, file contents, thinking, system text and the summary Claude Code writes when it
  compacts a session; of a command it keeps only the command line. API keys, tokens, private keys and
  `password=…` values become `[redacted]` before anything is stored.
- Text inside `<private>…</private>` is not stored; the rest of the message is. `COGITO_MEM_CAPTURE=off` (for
  example under `"env"` in `~/.claude/settings.json`) pauses capture; `COGITO_MEM_CAPTURE_ACTIONS=off` keeps
  messages only.
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
[`docs/requirements.md`](requirements.md).
