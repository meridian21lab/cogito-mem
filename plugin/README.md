# cogito-mem

**Long-term memory for Claude Code, on your own machine.** Cogi the squirrel keeps every message you and Claude exchange, and brings back what Claude forgot. No API key, no cloud, no AI calls to store.

![Cogi the squirrel: Claude forgets. Cogi doesn't.](cogi-card.png)

## Why try it

- **Claude stops forgetting.** Every message and reply is kept word for word, with its date. When something has dropped out of the context window, or happened last week, the relevant part comes back with your next prompt.
- **It remembers what you did, too.** The commands you ran (and whether they failed) and the files you touched, without their output.
- **Private and free.** One folder on your computer. No account, no API key, no AI calls to save a message. Nothing leaves your machine.
- **Tested.** On LongMemEval-S, the past session holding the answer is among the first five Cogi finds for 99.0% of 500 questions, with no AI model involved; other local memory plugins published 95.2–98.0% as of October 2026. On LoCoMo, the 1,000 tokens Cogi hands back answer 74.7% of questions right, level with rereading the whole conversation (76.5%). A search over 10 million tokens takes 26 ms on a laptop CPU. [See the results](https://meridian21lab.github.io/cogito-mem/results.html).

## Before you install

Cogi needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (on a Mac: `brew install uv`), on macOS or Linux (Windows is experimental). The first start downloads the model (310 MB, about a minute). From a terminal, the plugin installs with `claude plugin install cogito-mem --marketplace meridian21lab/cogito-mem`.

## Try it

1. Tell Claude: *Let's call the staging server "acorn".*
2. Clear its short-term memory: `/clear`
3. Ask: *What did we call the staging server?* Claude answers "acorn": Cogi brought it back.

## What Cogi runs, downloads and stores

- **Runs:** four Claude Code hooks and one MCP server, `cogi`. Each runs the released `cogito-mem` package from PyPI at the exact version this plugin pins (`uvx cogito-mem==<version>`); the plugin's `uv.lock` lists that release and numpy with their checksums. After each reply and at the end of a session, the hooks save the new messages from the session's transcript. At the start of a session and with each prompt, they add the few most relevant memories (at most 300 tokens per prompt). The MCP server gives Claude two tools, `memory_query` and `memory_append`, answered by a small service that listens on your computer only (`127.0.0.1:7327`).
- **Downloads, once, over HTTPS:** `cogito-mem` and its one dependency, numpy, from PyPI (by uv); llama.cpp's `llama-server` from llama.cpp's official GitHub releases (skipped if you already have it); and the EmbeddingGemma 2 model (310 MB) from Hugging Face. After that, Cogi makes no network calls.
- **Stores:** everything in `~/.cogito-mem/` on your computer: your messages, and a short note of what each turn did, in one SQLite file. API keys, tokens, private keys and passwords are replaced with `[redacted]` before anything is saved; tool output and file contents are never saved. Text inside `<private>…</private>` is skipped, and `COGITO_MEM_CAPTURE=off` pauses saving.
- **Sends:** nothing. No account, no analytics, no telemetry. (The package's optional benchmark command, `cogito-mem eval locomo-qa`, which only you would run, sends benchmark questions to the LLM API you set up for it, with your own key.)
- **Removes cleanly:** `claude plugin uninstall cogito-mem@cogito-mem`, then delete `~/.cogito-mem`.

The source of every release is at [github.com/meridian21lab/cogito-mem](https://github.com/meridian21lab/cogito-mem). Every file, download and connection, with links to the source: [What you install](https://meridian21lab.github.io/cogito-mem/safety.html).

## Learn more

| | |
|---|---|
| [How it works](https://meridian21lab.github.io/cogito-mem/how.html) | Collect, keep, find: what Cogi stores and how it finds it |
| [Results](https://meridian21lab.github.io/cogito-mem/results.html) | The numbers, and how to reproduce them |
| [API & MCP](https://meridian21lab.github.io/cogito-mem/api.html) | HTTP, Python, terminal and the two MCP tools |
| [Privacy](https://meridian21lab.github.io/cogito-mem/privacy.html) · [Terms](https://meridian21lab.github.io/cogito-mem/terms.html) | What Cogi collects (nothing) and the terms of use |
| [Questions and problems](https://github.com/meridian21lab/cogito-mem/issues) | Open an issue; feedback is very welcome |

## License

[MIT](https://github.com/meridian21lab/cogito-mem/blob/main/LICENSE)
