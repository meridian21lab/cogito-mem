# cogito-mem

<!-- mcp-name: io.github.meridian21lab/cogito-mem -->

**Long-term memory for Claude Code, on your own machine.** Cogi the squirrel keeps every message you and Claude
exchange, and brings back what Claude forgot. No API key, no cloud, no AI calls to store.

[![Cogi: Claude forgets. Cogi doesn't.](https://raw.githubusercontent.com/meridian21lab/cogito-mem/main/site/assets/cogi-card.png)](https://meridian21lab.github.io/cogito-mem/)

[![docs](https://img.shields.io/badge/docs-cogi-c8621a)](https://meridian21lab.github.io/cogito-mem/)
[![tests](https://github.com/meridian21lab/cogito-mem/actions/workflows/tests.yml/badge.svg)](https://github.com/meridian21lab/cogito-mem/actions/workflows/tests.yml)
![license](https://img.shields.io/badge/license-MIT-blue)

## Why try it

- **Claude stops forgetting.** Every message and reply is kept word for word, with its date. When something has
  dropped out of the context window, or happened last week, the relevant part comes back with your next prompt.
- **It remembers what you did, too.** Commands you ran (and whether they failed) and files you touched, without
  their output.
- **Private and free.** One folder on your computer. No account, no API key, no AI calls to save a message, nothing
  leaves your machine.
- **Tested.** On the LoCoMo benchmark, the 1,000 tokens Cogi hands back answer 74.7% of questions right, level with
  rereading the whole conversation (76.5%). A search over 10 million tokens takes 26 ms on a laptop CPU.
  [See the results](https://meridian21lab.github.io/cogito-mem/results.html).

## Install

With [uv](https://docs.astral.sh/uv/) installed, one command in a terminal:

```sh
claude plugin install cogito-mem --marketplace meridian21lab/cogito-mem
```

That's it. To get updates, turn on auto-update once: `/plugin` → *Marketplaces* → *cogito-mem* → *Enable
auto-update*. The first start downloads the model (310 MB, about a minute).
[Step-by-step guide](https://meridian21lab.github.io/cogito-mem/start.html) · [Codex, Claude Desktop, Docker](docs/install.md)

## Try it

1. Tell Claude: *Let's call the staging server "acorn".*
2. Clear its short-term memory: `/clear`
3. Ask: *What did we call the staging server?* Claude answers "acorn": Cogi brought it back.

## How it compares

| | cogito-mem | [claude-mem](https://github.com/thedotmack/claude-mem) | [Mem0 plugin](https://github.com/mem0ai/mem0/tree/main/integrations/claude-code-plugin) | [cognee plugin](https://github.com/topoteretes/cognee-integrations) | [Supermemory plugin](https://github.com/supermemoryai/claude-supermemory) |
|---|---|---|---|---|---|
| AI calls to store a message | **none** | an observer model per tool call (Haiku on your Claude plan by default) | extraction on Mem0's servers | extraction with your LLM key or `claude -p` | in Supermemory's service |
| Account or API key | **none** | optional sign-in | Mem0 Platform API key | an LLM key or the Claude CLI | API key or login |
| Where your memory lives | **your computer** | your computer (cloud sync optional) | Mem0's cloud | your computer (cloud optional) | Supermemory's cloud (local mode available) |
| What comes back | **your exact words, with dates** | AI-written observations | extracted memories | graph facts and summaries | extracted memories |
| Searchable after | **the same turn** | the observer's run | a batch (every 5 exchanges) | the next graph run | the background save |

Keep your project's rules in `CLAUDE.md`, and let Cogi remember what happened.

## Learn more

| | |
|---|---|
| [How it works](https://meridian21lab.github.io/cogito-mem/how.html) | Collect, keep, find: what Cogi stores and how it finds it |
| [Results](https://meridian21lab.github.io/cogito-mem/results.html) · [Benchmarks](docs/benchmarks.md) | The numbers, and how to reproduce them |
| [API & MCP](https://meridian21lab.github.io/cogito-mem/api.html) · [Reference](docs/reference.md) | HTTP, Python, terminal, settings, FAQ, roadmap |
| [What you install](https://meridian21lab.github.io/cogito-mem/safety.html) · [Privacy](https://meridian21lab.github.io/cogito-mem/privacy.html) | Every file, download and connection |
| [Development](docs/development.md) | Running the tests and the evaluations |

> **Early access.** v0.2 is new, built and tested (about 200 tests), and still being measured. Feedback and
> [issues](https://github.com/meridian21lab/cogito-mem/issues) are very welcome.

## License

[MIT](LICENSE)
