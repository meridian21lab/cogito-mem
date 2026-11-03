# Changelog

What changed in each version of Cogi (cogito-mem), for people who use it.

## 0.3.0 — 3 Nov 2026

**Update note:** Cogi now keeps a few lines of command output and what each sub-agent reports, where 0.2 kept neither. To keep messages only, set `COGITO_MEM_CAPTURE_TOOL_OUTPUT=off` and `COGITO_MEM_CAPTURE_SUBAGENTS=off`. Restart Claude Code after updating.

- **Searches fill their budget.** A search used to stop at 10 results, often well short of its token budget. It now returns up to 300 and lets the budget decide. `memory_query` reads 2,500 tokens when Claude gives no budget, up from 1,000.
- **A new note with each prompt.** Recall now shows the best few matches at more length, then one-line pointers to others. `COGITO_MEM_RECALL_DESIGN=shipped` brings back the old note.
- **New tool: `memory_open`.** Claude can open a message a pointer names and read the messages around it.
- **Remembers command results and sub-agent reports.** From each command, the lines that say how it went: errors, metrics, how a long run ended. Files Claude reads are still not stored.
- **Past sessions, if you want them.** `COGITO_MEM_BACKFILL=on` reads sessions from before you installed Cogi in the background, when a session starts and at most hourly.
- **Stays up between prompts.** The service waits 12 idle hours before stopping, not one, and a prompt that finds it down starts it again.
- **Cleaner recall.** Text Claude Code wrote, which older versions stored, no longer appears in recall.
- **Published results on 1M+ token histories.** On LongMemEval's long test, about 1.2M tokens per question, Cogi finds the right past session in its top 5 for 93.0% of 500 questions, ahead of four other local memory plugins run on the same questions. See the [results page](https://meridian21lab.github.io/cogito-mem/results.html).
- **No reranker option.** `cogito-mem serve --reranker` and `COGITO_MEM_RERANKER` are gone, and `serve --reranker` now stops with an error. Cogi runs its plain hybrid search, which needs no setup. On a slow machine or with several prompts at once, the option could leave a prompt with no memory at all.

## 0.2.1 — 21 Oct 2026

**Update note:** the plugin now runs `uvx cogito-mem==0.2.1`, so you need [uv](https://docs.astral.sh/uv/) on your PATH. Restart Claude Code after updating.

- **Installs from PyPI.** The plugin runs the released package instead of code from the repository. To install it yourself: `uv tool install cogito-mem`. The `curl | sh` install scripts are gone.
- **Smaller plugin.** The plugin is now its own folder holding only what it needs to run. Docs, tests and benchmarks are no longer copied into your plugin cache.
- **Published results.** On LongMemEval-S, Cogi finds the right past session in its top 5 results 99.0% of the time. The [results page](https://meridian21lab.github.io/cogito-mem/) shows where that sits among other local memories.
- **Clearer policies.** The privacy policy now lists everything Cogi stores, including the note it keeps of each turn's work. There is also a new terms of use page.

## 0.2.0 — 20 Oct 2026

**Update note:** your memory is renamed from `default` to `<username>-hollow` the first time 0.2.0 starts. Restart every open Claude Code session after updating. An older session still running 0.1.0 keeps writing to `default`.

- **Name your memory.** The plugin asks for a name when you enable it. Leave it empty to get `<username>-hollow`.
- **Remembers what Claude did, not only what was said.** Each turn gets a short note listing the commands it ran and the files it touched. Command output is never stored. Turn this off with `COGITO_MEM_CAPTURE_ACTIONS=off`.
- **`<private>…</private>` is never stored**, and `COGITO_MEM_CAPTURE=off` pauses capture.
- **More context by default.** Each recall brings back up to 1,000 tokens, up from 300.
- **The MCP server is now called `cogi`.** Tool names changed from `mcp__plugin_cogito-mem_cogito-mem__*` to `mcp__plugin_cogito-mem_cogi__*`. Update any permission rules that name them.
- **Fixed:** fresh installs fell back to keyword-only search because llama.cpp stopped attaching binaries to its "latest" release.
- **Fixed:** Claude Code's compaction summaries and task notifications were saved as if you had typed them.
- **Better secret redaction.** Bearer tokens, passwords in URLs and `*_API_KEY=` lines are now redacted.
- **Published** on PyPI and in the MCP Registry.

## 0.1.0 — 19 Oct 2026

First release.

- **Local long-term memory.** Every message between you and Claude is kept word for word, with the time it was said. Nothing leaves your machine, and no API key is needed.
- **Fast search.** Cogi searches by keyword and by meaning (EmbeddingGemma running in llama.cpp) and answers in milliseconds, even with millions of tokens stored.
- **Recall without being asked.** Each prompt gets the relevant memories added, and each new session starts with the end of your last one in the same project.
- **MCP tools** `memory_query` and `memory_append`, for Claude Code and other MCP clients.
- **Import your history** from claude.ai and ChatGPT data exports.
- **Ways to install:** the Claude Code plugin, a Docker image, or the CLI. Run `cogito-mem doctor` to check your setup.
