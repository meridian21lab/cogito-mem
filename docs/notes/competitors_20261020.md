# Cogito-mem competes on substance, not visibility

cogito-mem's closest competitors are not the big memory platforms. They are a few small Claude Code plugins built the same way: **deja-vu, iai-personal-memory-engine and MemPalace** keep the conversation text itself, run locally and make no LLM calls. Beyond them sit **claude-mem**, the popularity leader with 101,876 GitHub stars, and **Claude Code's built-in auto memory**, which every user already has. On functionality cogito-mem holds a defensible position. Every hook-based plugin from cognee, Mem0, Supermemory, Hindsight, Honcho and Letta sends captured text to an LLM or a vendor cloud. cogito-mem does neither, needs no API key, makes a turn searchable within milliseconds and adds at most 300 tokens to a prompt. What it lacks is a viewer, capture of tool calls, sync and team memory, and any way to reach claude.ai. On visibility it barely exists: 0 stars, no topics, no PyPI package, and no listing in any Anthropic marketplace, the MCP Registry or the awesome lists. Its manifest would also fail two blocking checks in Anthropic's directory review. That matters because a catalog listing, not stars, drives installs: `remember`, the only memory plugin in Anthropic's official marketplace, has **51,442 installs on 201 stars**. On evaluations, cogito-mem's self-reported LoCoMo score under the original Mem0-paper protocol is 74.7 at 1,000 tokens, measured 19 Oct 2026. That is above every system in that paper, full context included. But it comes from a single run that cogito-mem made itself, and in the same run cogito-mem's own full-conversation baseline scored 3.6 points above the paper's. There are no numbers yet on LongMemEval, BEAM or coding tasks, the benchmarks its rivals actually publish. The fastest gains are to fix the manifest and submit to Anthropic's directory, publish on PyPI and the MCP Registry, and add LongMemEval-S retrieval numbers.

*Unless marked otherwise, star counts, listings and catalog sizes were checked on 20 Oct 2026, and benchmark numbers are self-reported by the vendor named. "[self]" means a vendor measuring itself, "[competitor]" a rival vendor measuring it, and "[third-party]" a party with no product at stake.*

## Thirty-plus tools compete, but only a handful share cogito-mem's design

By October 2026 **at least 30 memory tools target Claude Code users**, and most of them also serve Codex, Cursor or OpenCode. The tools differ mainly in what happens to a session after it is captured:

- **LLM-distilled stores** (claude-mem, remember, claude-memory-compiler) send sessions or tool calls to a model that writes compressed observations or summaries.
- **Agent-curated notes** (Claude Code's auto memory, engram, the MCP reference memory server) keep only what the model chooses to save.
- **Verbatim transcript indexes** (MemPalace, deja-vu, iai-personal-memory-engine, episodic-memory) keep the words themselves and search them locally. This is cogito-mem's group.

All of this comes from the GitHub inventory taken on 20 Oct 2026 ([claude-mem](https://github.com/thedotmack/claude-mem); [MemPalace](https://github.com/MemPalace/mempalace); [deja-vu](https://github.com/vshulcz/deja-vu)). Around these plugins sit the general memory platforms, and almost all of them now ship an **official hook-based Claude Code plugin**: cognee, Mem0, Supermemory, Hindsight, Honcho, and Letta as a demo ([cognee plugin](https://github.com/topoteretes/cognee-integrations/blob/main/integrations/claude-code/README.md); [Mem0 plugin](https://github.com/mem0ai/mem0/blob/main/integrations/claude-code-plugin/README.md); [Hindsight plugin](https://github.com/vectorize-io/hindsight/blob/main/hindsight-integrations/claude-code/README.md)).

| Competitor | GitHub stars | How it remembers | Relevance to cogito-mem |
|---|---|---|---|
| [Claude Code auto memory](https://code.claude.com/docs/en/memory) | built in (since v2.1.59, 25 Feb 2026) | Claude writes notes to MEMORY.md and topic files | The default; it complements cogito-mem rather than replacing it |
| [claude-mem](https://github.com/thedotmack/claude-mem) | 101,876 | An LLM writes observations for each tool call, plus session summaries | Popularity leader |
| [MemPalace](https://github.com/MemPalace/mempalace) | 59,654 | Verbatim "drawers", local, no LLM | Same design philosophy, about 60k stars |
| [agentmemory](https://github.com/rohitg00/agentmemory) | 29,701 | Heuristic compression, BM25 (plus optional vectors) | Per-prompt injection, viewer |
| [deja-vu](https://github.com/vshulcz/deja-vu) | 1,256 | Indexes existing transcripts, no LLM | **Closest design**: per-prompt recall, no key |
| [iai-pme](https://github.com/CodeAbra/iai-personal-memory-engine) | 912 | Every turn verbatim, local | **Closest design**: per-turn recall pack |
| [episodic-memory](https://github.com/obra/episodic-memory) | 492 | Archived transcripts with local embeddings | Distributed through the superpowers marketplace |
| [remember](https://github.com/Digital-Process-Tools/claude-remember) | 201 | Haiku summaries in tiered daily logs | The only memory plugin in Anthropic's official marketplace |
| [cognee](https://github.com/topoteretes/cognee) | 32,575 | Knowledge graph plus vectors, LLM on ingest | Platform rival named in the brief; official hook plugin |
| [Mem0](https://github.com/mem0ai/mem0) | 67,508 | LLM fact extraction; the plugin needs the cloud | In Anthropic's community marketplace |
| [Hindsight](https://github.com/vectorize-io/hindsight) | 51,853 | LLM fact extraction, local daemon | The only plugin with a coding-agent benchmark |
| [Supermemory](https://github.com/supermemoryai/supermemory) | 31,327 (plugin repo 2,793) | Cloud fact extraction | Per-prompt recall, team memory |
| [Honcho](https://github.com/plastic-labs/honcho) | 7,698 | An LLM "deriver" reasons over stored messages | History import, hosted MCP |
| [Graphiti / Zep](https://github.com/getzep/graphiti) | 32,069 | Temporal knowledge graph, MCP tools only | Strongest time model, no capture plugin |
| [Basic Memory](https://github.com/basicmachines-co/basic-memory) | 4,287 | Markdown notes written by the model | Local, no LLM on the server side |

Treat star counts as noise rather than usage: many repos in this space went from zero to 1k–100k stars during 2026, and no plugin publishes active-install counts. Claude Code's auto memory works alongside cogito-mem rather than in its place. It loads the first 200 lines or 25 KB of MEMORY.md at session start, and "skips anything it can derive from the codebase". It offers **no search over past transcripts** ([Claude Code docs](https://code.claude.com/docs/en/memory)). Not every rival leaves it alone, though: cognee's plugin, in cloud mode, sets `autoMemoryEnabled: false` and so turns Claude Code's own memory off ([cognee plugin README](https://github.com/topoteretes/cognee-integrations/blob/main/integrations/claude-code/README.md)).

## Keeping the words, needing no key and recalling instantly is rare, but not unique

### Against local plugins, cogito-mem trades breadth for a cleaner retrieval core

cogito-mem saves the user's typed messages and the assistant's text replies word for word after every turn, through its Stop and SessionEnd hooks. They go into an append-only SQLite log. Tool calls, thinking and system text are skipped, and secrets are redacted before anything is stored. Search fuses BM25 with EmbeddingGemma 2, an embedding model that runs locally through llama.cpp, and neither storing nor searching calls an LLM. Recall is automatic. On each prompt, cogito-mem adds up to 300 tokens of the best matches from earlier sessions; matches from the current project come first, and nothing is added when no match is strong enough. At session start, it adds how the last session in the project ended ([cogito-mem README](https://github.com/meridian21lab/cogito-mem)).

| | cogito-mem | Claude Code auto memory | claude-mem | deja-vu | iai-pme | MemPalace | agentmemory | episodic-memory |
|---|---|---|---|---|---|---|---|---|
| **What is stored** | User and assistant text, verbatim | Notes written by Claude | LLM observations; raw prompts; tool I/O backup | Existing transcripts, indexed in place | Every turn, verbatim | Verbatim drawers | Observations; replayable sessions | Archived transcripts |
| **LLM on the write path** | None | Main session model | Haiku by default (or the hosted observer) | None | None (optional nightly `claude -p`) | None | Optional | Haiku summaries, for display only |
| **Search** | BM25 + EmbeddingGemma 2, rank-fused | None (index file plus file reads) | FTS5 + optional Chroma | Lexical; embeddings optional via Ollama etc. | Semantic + graph + lexical + recency | Chroma semantic (+ hybrid) | BM25 (+ MiniLM + graph) | bge-small vectors + substring match |
| **Automatic recall** | Every prompt, ≤300 tokens; session start | Session start, 200 lines / 25 KB | Session start, 50 observations; per-prompt is off by default | Session start, each prompt, before tools, after failed commands | Session start plus a per-turn pack (~350 tokens on average) | `wake-up` command; per-prompt not stated | Each prompt, 2,000-token budget | None (on demand through a skill) |
| **History from before install** | Yes (Claude Code, Codex, claude.ai and ChatGPT exports) | No | Not documented | Yes | Not stated | Yes (`mine`) | Not stated | Yes |
| **Tool calls and commands** | No, by design | No | Yes | Yes (files, commands, exit codes, edits) | — | — | Yes (Replay) | — |
| **Viewer** | None (CLI, HTTP and Python APIs) | `/memory` opens the files | Web viewer, TeamBrain | TUI | `iai brain` dashboard | Not stated | 12-tab web viewer | HTML export |

Sources: [Claude Code docs](https://code.claude.com/docs/en/memory); [claude-mem README](https://github.com/thedotmack/claude-mem/blob/main/README.md) and [configuration](https://github.com/thedotmack/claude-mem/blob/main/docs/public/configuration.mdx); [deja-vu](https://github.com/vshulcz/deja-vu); [iai-pme](https://github.com/CodeAbra/iai-personal-memory-engine); [MemPalace](https://github.com/MemPalace/mempalace); [agentmemory](https://github.com/rohitg00/agentmemory); [episodic-memory](https://github.com/obra/episodic-memory). All READMEs were read on 20 Oct 2026.

The clearest advantage is **cost**. LLM-distilled memory runs up bills in the background, and users have documented it:

- One claude-mem user tracked a month of usage and found the memory observer cost **$65.82 on top of $102.94 of actual coding spend, 63.9% extra** (issue filed 2 Sep 2026) ([#3848](https://github.com/thedotmack/claude-mem/issues/3848)).
- Another reported the observer **burned 76M+ tokens in one day** and exhausted their Claude Code limit (5 May 2026) ([#2315](https://github.com/thedotmack/claude-mem/issues/2315)).
- claude-mem's hosted observer averaged about **13× more input tokens per observation** than Haiku (17 Oct 2026) ([#4847](https://github.com/thedotmack/claude-mem/issues/4847)).
- episodic-memory has an open bug, filed 6 Oct 2026, where repeated launches turn its summary backlog into "a nonstop Haiku loop" ([#188](https://github.com/obra/episodic-memory/issues/188)).

Cost also explains why the most popular plugin's best recall path is switched off: claude-mem's per-prompt injection (`CLAUDE_MEM_SEMANTIC_INJECT`) defaults to false ([configuration](https://github.com/thedotmack/claude-mem/blob/main/docs/public/configuration.mdx)). cogito-mem turns per-prompt recall on by default and keeps it to 300 tokens. That is less than iai's ~350-token average and far below agentmemory's 2,000-token default ([iai-pme](https://github.com/CodeAbra/iai-personal-memory-engine); [agentmemory](https://github.com/rohitg00/agentmemory)).

cogito-mem's retrieval core is also more complete out of the box than its peers':

- episodic-memory's text mode is "a single case-insensitive substring" search, not BM25 ([episodic-memory](https://github.com/obra/episodic-memory)).
- deja-vu's semantic recall needs an external embedding endpoint ([deja-vu](https://github.com/vshulcz/deja-vu)).
- MemPalace defaults to MiniLM and offers EmbeddingGemma only as an option ([MemPalace](https://github.com/MemPalace/mempalace)).

cogito-mem's `memory_query` tool also offers time travel (`as_of`) and validity windows (`valid_after` / `valid_before`). Among local plugins only iai has anything comparable, its validity windows closed by `memory_contradict`.

The honest counterweight is **deja-vu**. With 1,256 stars it shares cogito-mem's whole philosophy: no LLM, local, per-prompt recall, no key. It is also broader:

- It indexes the files each turn opened, the commands run with their exit status, and edit spans. Its `fix`, `blame` and `how` modes answer questions like "how did we fix this last time".
- It covers 42 agents.
- It ships a TUI and `deja sync ssh`.

([deja-vu](https://github.com/vshulcz/deja-vu)). For a coding memory, that breadth is the strongest functional argument against cogito-mem's choice to skip tool calls.

### Against the platforms, cogito-mem gives up structure to avoid LLM calls, API keys and recall lag

| Platform plugin | What it needs | LLM on the write path | Automatic recall | How soon a new turn is recallable | Fully local option |
|---|---|---|---|---|---|
| [cognee](https://github.com/topoteretes/cognee-integrations/blob/main/integrations/claude-code/README.md) `cognee-memory@cognee` | Python 3.10–3.14 venv with cognee 1.6.5; an LLM key or `claude -p` | Yes: the graph is built by "improve" runs every 150 events and at SessionEnd | Each prompt, plus code-graph facts when a file is read | Raw turns go to a session tier; explicit remembers are "not recallable immediately" | Yes, with your own LLM key, or with `claude -p` runs that "count against usage limits" |
| [Mem0](https://github.com/mem0ai/mem0/blob/main/integrations/claude-code-plugin/README.md) `mem0@mem0-plugins` | Mem0 Platform API key | Yes, server side | **First prompt of a session only** (up to 5 memories) | Flushed every 5 exchanges or after 5 idle minutes | No |
| [Supermemory](https://github.com/supermemoryai/claude-supermemory) | API key or login | Yes, in the cloud | Each substantive prompt | Background capture on Stop | Local server exists; the plugin defaults to the cloud |
| [Hindsight](https://github.com/vectorize-io/hindsight/blob/main/hindsight-integrations/claude-code/README.md) `hindsight-memory` | `uvx` daemon plus an LLM key or the `claude-code` provider | Yes, fact extraction | Each prompt, 1,024 tokens of consolidated "observations" | **Every 10 turns** by default | Yes, with an LLM |
| [Honcho](https://github.com/plastic-labs/claude-honcho) | `hch-` API key, Node | Yes (the "deriver") | Each prompt | Each message is saved on prompt submit; derived memory comes later; upload and summary at SessionEnd | Self-hosting needs Postgres and an LLM key |
| [Letta Claude Subconscious](https://github.com/letta-ai/claude-subconscious) | `LETTA_API_KEY`; labeled "demo… not intended to be used in production" | An agent reads the whole transcript | Agent-written "whispers", not stored records | After each response | Self-host only |
| [Graphiti MCP](https://github.com/getzep/graphiti/blob/main/mcp_server/README.md) | Docker, FalkorDB or Neo4j, an OpenAI key | "Multiple LLM calls" per episode | None; the model must call tools | After extraction | Yes, but "do not use… as a production deployment" |
| [Basic Memory](https://github.com/basicmachines-co/basic-memory) | Python 3.12+, `--prerelease=allow` | No (the model writes notes) | Session-start briefings | Immediate (notes written by the model) | Yes |

All READMEs were read on 20 Oct 2026.

**Every hook-based platform plugin except Basic Memory sends captured session text either to a vendor cloud or to an LLM**, and often the LLM is the user's own Claude subscription called through `claude -p`. None of them makes the verbatim session its system of record. cognee comes closest: it keeps raw session messages as a staging tier that feeds graph extraction. Freshness is where cogito-mem's design pays off most visibly. A cogito-mem turn is **searchable by keyword at once and by meaning about 13–57 ms later**. In Hindsight the same turn may wait up to 10 turns to be stored. In Mem0 it waits for 5 exchanges, and Mem0 only injects memories on a session's first prompt. cognee's per-prompt hook includes a readiness probe with a 3.0 s timeout ([Hindsight plugin](https://github.com/vectorize-io/hindsight/blob/main/hindsight-integrations/claude-code/README.md); [Mem0 plugin](https://github.com/mem0ai/mem0/blob/main/integrations/claude-code-plugin/README.md); [cognee plugin](https://github.com/topoteretes/cognee-integrations/blob/main/integrations/claude-code/README.md)). Privacy differs just as sharply. Mem0 sends user messages, Claude's answers and changed file paths to its servers, and its telemetry is "not anonymous when an API key is configured". Supermemory says its own credential filter "cannot detect every secret" ([Mem0 plugin](https://github.com/mem0ai/mem0/blob/main/integrations/claude-code-plugin/README.md); [claude-supermemory](https://github.com/supermemoryai/claude-supermemory)).

The platforms' best counter-argument is that verbatim recall returns noisy chunks while distilled facts are compact and handle contradictions:

- Supermemory supersedes old facts with newer ones ([README](https://github.com/supermemoryai/supermemory/blob/main/README.md)).
- Hindsight returns "consolidated beliefs rather than raw facts" ([plugin](https://github.com/vectorize-io/hindsight/blob/main/hindsight-integrations/claude-code/README.md)).

The independent evidence on this point leans toward cogito-mem's bet but does not settle it:

- A June 2026 controlled study (abstract only) found that verbatim RAG roughly matched full context on LongMemEval-S (47.2% vs 49.8%, p = 0.34) and that swapping only the embedding model moved accuracy by 6.2 points. Mem0 matched cloud-embedding RAG on 2 of 6 question types at about 50× the cost ([MemDelta, arXiv 2606.29914](https://arxiv.org/abs/2606.29914)).
- hippo-memory reports that its own "sleep" consolidation lowered hit@5 by 3.6 points [self] ([hippo-memory](https://github.com/kitfunso/hippo-memory)).

### The real gaps, and three that only look like gaps

Three features that rivals advertise as selling points already exist in cogito-mem:

- **Importing history from before install.** `cogito-mem capture claude-code --all` plus claude.ai and ChatGPT data exports cover it, and Codex sessions are captured too. That puts cogito-mem level with deja-vu, episodic-memory, MemPalace's `mine` and Honcho's `/honcho:import`.
- **Secret redaction.** API keys, tokens, private keys and passwords are replaced before storage, as deja-vu, cognee, Mem0 and Supermemory also do.
- **Filters.** `memory_query` filters by author, thread and validity window.

([cogito-mem README](https://github.com/meridian21lab/cogito-mem)). Rivals advertise these features, so cogito-mem's listing should state them up front. The gaps that remain are these:

| Missing in cogito-mem | Who ships it | Weight for a Claude Code memory |
|---|---|---|
| Capture of tool calls, commands and files touched | claude-mem, deja-vu, agentmemory, cognee; Mem0 (changed file paths, failed-command details); Hindsight | **High**: coding recall often depends on "what we ran and what failed" |
| Viewer showing what was stored and injected | claude-mem, agentmemory (12-tab viewer with Replay), deja-vu and engram (TUI), iai (`iai brain`), Supermemory "recall strip" | Medium; it builds trust. Viewers are also an attack surface (projectmem fixed a stored XSS ([projectmem](https://github.com/riponcm/projectmem))) |
| Opt-out marker or pause | claude-mem `<private>` tags, episodic-memory's DO-NOT-INDEX marker, Mem0 `/mem0:pause` | Medium, and cheap to build. Not documented in cogito-mem's README, which describes only automatic redaction |
| Sync across machines | claude-mem cloud sync, deja-vu `sync ssh`, engram Git Sync, memorix relays, Basic Memory Cloud | Medium |
| More agents (Cursor, OpenCode, Gemini CLI…) | deja-vu (42 agents), claude-mem, episodic-memory, memsearch | Medium |
| Remote MCP for claude.ai and Cowork | Supermemory, Honcho, Zep hosted MCP endpoints; Mem0 in Cowork | Medium; it conflicts with "nothing leaves your machine" |
| Team or shared memory | Supermemory repo containers, Mem0 project memory, Honcho workspaces, claude-mem TeamBrain | Low to medium |
| Knowledge graph, summaries, consolidation | cognee, Graphiti, Hindsight, Mem0 (Pro tier), MemPalace temporal KG | **Low**: costly, and the evidence above is mixed |

Sources: [claude-mem](https://github.com/thedotmack/claude-mem/blob/main/README.md); [deja-vu](https://github.com/vshulcz/deja-vu); [agentmemory](https://github.com/rohitg00/agentmemory); [episodic-memory](https://github.com/obra/episodic-memory); [Mem0 plugin](https://github.com/mem0ai/mem0/blob/main/integrations/claude-code-plugin/README.md); [claude-supermemory](https://github.com/supermemoryai/claude-supermemory); [claude-honcho](https://github.com/plastic-labs/claude-honcho).

## Catalog placement, not stars, decides installs, and cogito-mem has none

Anthropic runs two routes into Claude Code, and they reach very different numbers of users.

The **official marketplace** (`claude-plugins-official`, 315 plugins):

- Is added to every Claude Code install the first time an interactive session starts, and auto-updates by default ([Anthropic's marketplaces](https://code.claude.com/docs/en/plugins/anthropic-marketplaces); [Install and manage plugins](https://code.claude.com/docs/en/discover-plugins)).
- Its plugins have pages on claude.com that show install counts.
- Holds exactly one dedicated conversation-memory plugin, `remember`. On 20 Oct 2026 it had **51,442 installs** against 201 GitHub stars. claude-mem, with 101,876 stars, has no claude.com page at all (HTTP 404) ([claude.com/plugins/remember](https://claude.com/plugins/remember); [claude.com/plugins/claude-mem](https://claude.com/plugins/claude-mem); [official marketplace.json](https://github.com/anthropics/claude-plugins-official/blob/main/.claude-plugin/marketplace.json)).
- **Takes no submissions**; "If you work with an Anthropic partner contact, ask them about an official-marketplace listing" ([Publish and distribute a plugin](https://code.claude.com/docs/en/plugins/publish)).

The **claude.ai directory** is open to "anyone on a paid Claude plan":

- Every version gets "automated validation and a security scan", and "a person reviews a new listing before it goes live".
- Approval yields one listing across claude.ai, Cowork and Claude Code, plus a Usage tab with installs and error rates ([Publish to the directory](https://claude.com/docs/directory/publish)).
- The **community marketplace** describes itself as a nightly mirror of plugins "submitted via claude.ai" that passed automated security scanning and were approved. It held 2,283 plugins on 20 Oct 2026, about 133 of them memory-related, including claude-mem and mem0. Users must add this marketplace by hand ([claude-plugins-community](https://github.com/anthropics/claude-plugins-community); [community marketplace.json](https://github.com/anthropics/claude-plugins-community/blob/main/.claude-plugin/marketplace.json)).

Today cogito-mem uses neither. It relies on a third route, its own marketplace, and that has two costs. Its plugins appear in the `/plugin` Discover tab only after a user runs `/plugin marketplace add`, and **auto-update is off by default** for third-party marketplaces ([Install and manage plugins](https://code.claude.com/docs/en/discover-plugins)). So v0.1 users will not receive fixes unless they turn auto-update on.

| Channel | How to get in | Memory competitors listed (20 Oct 2026) | cogito-mem |
|---|---|---|---|
| Official marketplace (315 plugins, on by default) | Partner contact only | `remember` (51,442 installs); `claude-md-management` (287,247) | No |
| claude.ai directory and `claude-community` (2,283 plugins) | Submit from a paid plan; validation, security scan, human review | claude-mem, mem0, remember, ~130 others, including a `cognito` plugin ("A memory layer for Claude Code") | No |
| Own marketplace | `/plugin marketplace add` | cognee, Supermemory, Hindsight, Honcho, Letta, deja-vu, iai | **Yes, the only route today** |
| [MCP Registry](https://registry.modelcontextprotocol.io/v0/servers?search=memory&version=latest) (preview, 289 "memory" servers) | PyPI package with an `mcp-name` marker, or an OCI label | mem0 (remote), Letta (npm); **not** cognee or claude-mem | No |
| PyPI | Publish | basic-memory, mem0ai, cognee, graphiti-core | No (the name `cogito-mem` is free) |
| [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) (56,071 stars) | Web issue form; **≥100 stars and ≥14 days old** | 14 memory entries; not claude-mem, mem0, Supermemory or episodic-memory | No (old enough from ~1 Nov 2026) |
| [awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) (96,648 stars) | Alphabetical PR; 282 of 346 memory entries carry a Glama badge | basic-memory, cognee | No |
| [Docker MCP Catalog](https://github.com/docker/mcp-registry/blob/main/CONTRIBUTING.md) | PR; Docker review; live ~24 h after approval | `mcp/memory` 559,497 pulls; `neo4j-memory` 38,052; `basic-memory` 10,690 (last updated 2 May 2025) | GHCR image only |

Sources: listings as linked; MCP Registry ownership rules from [package-types.mdx](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx); Docker pull counts from the [Docker Hub API](https://hub.docker.com/v2/repositories/mcp/memory/). Smithery, Glama, PulseMCP, mcp.so and claudemarketplaces.com could not be reached, so their rankings are unverified.

The directory is the only open door that leads toward install numbers like `remember`'s, and **cogito-mem's manifest would not pass it today**. Its GitHub presence also does nothing to help:

- The repo, created 18 Oct 2026, has 0 stars, no topics, and the description "Agent fast and simple memory store".
- claude-mem, by contrast, tags itself `claude-code-plugin`, `ai-memory` and `long-term-memory`, and even uses competitor names (`mem0`, `supermemory`) as topics.
- claude-mem's README opens with a preview GIF, badges and a star-history chart.

([GitHub: claude-mem](https://github.com/thedotmack/claude-mem)). Checked against Anthropic's [pre-submission checklist](https://claude.com/docs/plugins/pre-submission-checklist), cogito-mem's [plugin.json](https://github.com/meridian21lab/cogito-mem/blob/main/.claude-plugin/plugin.json), [launcher](https://github.com/meridian21lab/cogito-mem/blob/main/scripts/cogito-mem-plugin) and [hooks](https://github.com/meridian21lab/cogito-mem/blob/main/hooks/hooks.json) look like this:

| Checklist rule | cogito-mem today | Result | Fix |
|---|---|---|---|
| `displayName` in one writing system, no invisible characters | "Cogi 🐿️ cogito-mem memory" contains U+FE0F, an invisible variation selector | **Blocks** | Use plain text, e.g. "Cogi – cogito-mem memory" |
| Pin packages; run `uv run` with `--locked` or `--frozen` | `uv run --quiet --no-dev --project …` | **Blocks** | Add `--frozen` (`uv.lock` is committed) |
| Start a local MCP server by running a file with plain arguments, not through a shell | `"command": "sh"` | Held for review | Make the script executable and call it directly |
| Keep launchers and package installs out of scripts that hooks and MCP servers run | Hooks and the MCP server all run a script that may create a uv environment | Held for review | Move setup to install time, or split it from the hot path |
| README ≥40 words, a license, small text-only files | ~2,850 words, MIT, 85 tracked files, none over 256 KiB or binary | Pass | — |
| "Describe in the README everything the plugin runs, sends, or fetches" | README says the only traffic is a one-time download of llama.cpp and the model | Likely pass | Name the hosts it downloads from |

Three smaller fixes matter as well:

- Add the directory-only fields `icon`, `documentationUrl`, `supportUrl` and `privacyPolicyUrl`. The directory reads them, Claude Code ignores them, and `remember` sets the three URL fields ([manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference); [remember plugin.json](https://github.com/Digital-Process-Tools/claude-remember/blob/main/.claude-plugin/plugin.json)).
- Add a `category` to the marketplace entry. 301 of 315 official entries have one ([official marketplace.json](https://github.com/anthropics/claude-plugins-official/blob/main/.claude-plugin/marketplace.json)).
- Settle the name now. The plugin `name` cannot be changed after publishing, and a `cognito` memory plugin already sits in the community catalog, which could trigger the reviewer hold "Name may be confused with an existing listing" ([claude-plugins-official README](https://github.com/anthropics/claude-plugins-official); [checklist](https://claude.com/docs/plugins/pre-submission-checklist)).

One open question: cogito-mem's core is its hooks, which are a Claude Code feature, and the research did not verify how a claude.ai or Cowork listing presents a hook-centric plugin.

## Under the strictest LoCoMo protocol cogito-mem leads, but only by its own measurement

Few published numbers can sit in the same column as cogito-mem's. To be comparable, a result has to use the original Mem0-paper protocol: gpt-4o-mini both answers and judges, on LoCoMo categories 1–4 (1,540 questions). cogito-mem measured itself under that protocol on 19 Oct 2026, on a MacBook Pro M5 Max with EmbeddingGemma 2 Q8_0 ([cogito-mem results](https://meridian21lab.github.io/cogito-mem/results.html)).

| System (LoCoMo, 1,540 questions, gpt-4o-mini) | J | Memory / context tokens | Reported by, date |
|---|---|---|---|
| **cogito-mem** | **65.3 / 74.7 / 76.9** | 300 / 1,000 / 2,500 | [self], 19 Oct 2026 ([results](https://meridian21lab.github.io/cogito-mem/results.html)) |
| cogito-mem harness, whole conversation (762 questions) | 76.5 | ~26K | [self], 19 Oct 2026 |
| Full context | 72.90 | 26,031 | Mem0 paper, 2025 ([arXiv 2504.19413](https://arxiv.org/abs/2504.19413)) |
| Mem0g | 68.44 | 3,616 | [self], 2025 ([Mem0 paper](https://arxiv.org/abs/2504.19413)) |
| Mem0 | 66.88 | 1,764 | [self], 2025 ([Mem0 paper](https://arxiv.org/abs/2504.19413)) |
| Zep, run by Mem0 | 65.99 | 3,911 | [competitor], 2025 ([Mem0 paper](https://arxiv.org/abs/2504.19413)) |
| Zep, own rerun | 75.14 | not stated | [self], blog seen via search snippet ([Zep blog](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)) |
| Memobase v0.0.37 | 75.78 | not stated | [self]; judge "e.g. gpt-4o" ([Memobase](https://github.com/memodb-io/memobase/tree/main/docs/experiments/locomo-benchmark)) |
| Letta file-system agent | 74.0 | agentic, several LLM calls per question | [self], 12 Aug 2025 ([Letta blog](https://www.letta.com/blog/benchmarking-ai-agent-memory)) |
| MemMachine v0.2 | 88.12 | not stated | [self], Dec 2025, its own prompts ([AMB external_results](https://github.com/vectorize-io/agent-memory-benchmark/blob/main/external_results.json)) |
| Best RAG (k=2, 256-token chunks) | 60.97 | ~512 | Mem0 paper, 2025 |

Read naively, the table is very favorable:

- At **300 tokens cogito-mem is within 1.6 points of Mem0, which used 1,764 tokens**.
- At 1,000 tokens it beats every row of the Mem0 paper, full context included.
- At 2,500 tokens it matches Zep's own rerun and Memobase.
- It stays well below MemMachine's self-reported 88.12, which used its own prompts.

Four caveats temper this, and the published write-up should state them:

1. Every cogito-mem number is **[self], from one run on one machine**. The Mem0 paper reports a mean ± std over repeated judge runs.
2. cogito-mem's whole-conversation control scored **76.5, 3.6 points above the paper's 72.90**, on only half the questions. Part of the margin may therefore be harness drift. The project's results page already corrects for this by reporting each score as a share of its own harness's whole-conversation score: **98% at 1,000 tokens, against 92% for Mem0 and 94% for Mem0g** ([results](https://meridian21lab.github.io/cogito-mem/results.html)). That is the fairer framing, though the 76.5 baseline still rests on 762 questions.
3. The Mem0 paper's category labels are permuted relative to the dataset ([Memobase harness](https://github.com/memodb-io/memobase/tree/main/docs/experiments/locomo-benchmark); [mem0 prompts.py](https://github.com/mem0ai/memory-benchmarks/blob/main/benchmarks/locomo/prompts.py)), so per-category comparisons need remapping.
4. LoCoMo itself is flawed. **6.4% of gold answers are wrong, capping a legitimate score at 93.57%.** The standard "be generous" gpt-4o-mini judge **accepts 62.81% of vague-but-topical wrong answers.** And changing only the answer model and prompt moves a full-context score from 74.29% to 92.62% ([locomo-audit](https://github.com/dial481/locomo-audit); [ap-baseline](https://github.com/dial481/locomo-audit/tree/main/ap-baseline); [fc-baseline](https://github.com/dial481/locomo-audit/tree/main/fc-baseline)).

That last point is why the 2026 headline numbers are effectively a different benchmark, and why cogito-mem should not be placed next to them without context.

| System | Headline LoCoMo | How it was measured | Same system in a rival's harness |
|---|---|---|---|
| Mem0 platform | 92.5 [self] | GPT-5 answers and judge; judge accepts one correct item from a list; ~7.0K tokens. **Its own committed result files give 91.56** ([results/platform](https://github.com/mem0ai/memory-benchmarks/tree/main/results/platform)) | 77.68 at 17,395 tokens (OmniMemEval) |
| Zep | 94.7 [self] | gpt-5.4 reader, 5,760 tokens (search snippet) ([getzep.com/research](https://www.getzep.com/research/)) | 63.83 at 1,862 tokens (OmniMemEval) |
| Hindsight | 92.01 [self] | Vectorize's own AMB harness, Gemini 3.1 Pro answers, **36,235 tokens**, more than a whole LoCoMo conversation ([AMB outputs](https://github.com/vectorize-io/agent-memory-benchmark/tree/main/outputs)) | 81.99 at 24,683 tokens (OmniMemEval) |
| cognee | 90.7 [self] | 1,762 questions: drops open-domain and 143 questions with corrupted golds, adds adversarial; gpt-5-mini answers, gpt-5.1 judge; run Oct 2026 ([locomo_summary](https://github.com/topoteretes/cognee/blob/main/cognee/eval_framework/locomo/report_artifacts/locomo_summary.md)) | 83.48 at 32,532 tokens (OmniMemEval); 80.26 on only 152 questions (AMB) |
| MemOS | 88.83 [self] | Its own OmniMemEval harness, gpt-4.1-mini answers, 5,400 tokens ([MemOS](https://github.com/MemTensor/MemOS)) | 80.76 (EverMemOS's run) |
| Supermemory | "#1" [self]; 77.1 "with GPT-4o" (13 Apr 2026) ([#795](https://github.com/supermemoryai/supermemory/issues/795)) | Judge not named | 73.53 at 15,238 tokens (OmniMemEval) |

OmniMemEval figures come from MemTensor's [results.md](https://github.com/MemTensor/OmniMemEval/blob/main/docs/user_memory/results.md) (HEAD 20 Oct 2026; gpt-4.1-mini answers, gpt-4o-mini judge) [competitor].

Vendor-run cross-harness snapshots disagree with self-reports by **15–30 points**, and each harness tends to crown its author: MemOS leads OmniMemEval and Hindsight leads AMB. cognee's own numbers do not use the Mem0-paper protocol at all. Its BEAM report scores just 20 questions per size, and the 10M routing was "in-sample exploratory" by cognee's own description ([BEAM REPORT](https://github.com/topoteretes/cognee/blob/main/cognee/eval_framework/beam/REPORT.md)). Self-reports fail to reproduce elsewhere too. A third party measured EverMemOS at 38.38% on 152 questions against a claimed 93% ([EverMemOS#73](https://github.com/EverMind-AI/EverMemOS/issues/73)). So cogito-mem is not behind on rigor. It is behind on **coverage of the benchmarks its rivals publish**.

| Claude Code plugin | Published evaluation (README, read 20 Oct 2026; all [self]) |
|---|---|
| claude-mem | None; only "~10x token savings" ([README](https://github.com/thedotmack/claude-mem)) |
| deja-vu | LongMemEval-S R@5 **97.2%**; LoCoMo hit@1 70.5% ([README](https://github.com/vshulcz/deja-vu)) |
| MemPalace | LongMemEval R@5 96.6% raw, a plain ChromaDB baseline per [mcp-memory-service](https://github.com/doobidoo/mcp-memory-service/blob/main/docs/BENCHMARKS.md); LoCoMo R@10 60.3% raw ([README](https://github.com/MemPalace/mempalace)) |
| iai-pme | LongMemEval-S R@5 96.2% ([README](https://github.com/CodeAbra/iai-personal-memory-engine)) |
| agentmemory | LongMemEval-S R@5 95.2% (BM25 only: 86.2%); a 15-query coding test ([README](https://github.com/rohitg00/agentmemory)) |
| mcp-memory-service | LongMemEval-S R@5 86.0%, 0 LLM calls ([BENCHMARKS.md](https://github.com/doobidoo/mcp-memory-service/blob/main/docs/BENCHMARKS.md)) |
| Hindsight plugin | **SDEBench**, 61 bug-fix tasks with Claude Code + sonnet-5, 3 runs: 0.28–0.41 vs 0.80–0.89 interventions per task, $0.32–0.35 vs $0.43–0.45 per task ([AMB sdebench](https://github.com/vectorize-io/agent-memory-benchmark/tree/main/outputs/sdebench)) |
| episodic-memory, basic-memory, memsearch | None |
| **cogito-mem** | LoCoMo QA (above); judge-free evidence coverage **39.0 / 56.5 / 72.5% at 100 / 300 / 1,000 tokens**; query p95 **26 ms at 10M tokens on CPU** (14 ms with Metal); appends 1–11 ms; 19 Oct 2026 ([results](https://meridian21lab.github.io/cogito-mem/results.html)) |

LongMemEval-S R@5 is the de facto metric among Claude Code plugins, and cogito-mem has no number for it. Only Hindsight has shown that memory helps a coding agent end to end, and it did so in its own vendor's harness. On latency, cogito-mem's 26 ms p95 should be compared only with other local, search-only figures:

- agentmemory: 14 ms p50 on 15 sessions.
- deja-vu: 0.7–0.8 ms median in process, ~15 ms on LongMemEval-S haystacks.

Cloud figures include network time and are not comparable. They run from Mem0's 0.200 s search p95 in its paper, to Zep's 0.632–0.778 s, to 6.0 s client-side p95 in Mem0's own 2026 top-200 result files ([agentmemory](https://github.com/rohitg00/agentmemory); [deja-vu](https://github.com/vshulcz/deja-vu); [Mem0 paper](https://arxiv.org/abs/2504.19413); [results/platform](https://github.com/mem0ai/memory-benchmarks/tree/main/results/platform)). What no competitor publishes is search latency at a stated 10M-token corpus. That claim belongs to cogito-mem, and so does the judge-free coverage metric, which sidesteps the leniency problem entirely.

## Conclusion

The market has converged on cogito-mem's integration pattern: SessionStart and per-prompt recall injection, capture on Stop. So "automatic capture plus recall" is now table stakes, not a differentiator. cogito-mem stands out for what it refuses to do (call an LLM, use a cloud, require a key) and for evaluating itself under the least inflated protocol in use. Its biggest risk is obscurity, not a missing feature. deja-vu already ships the same philosophy with broader capture, and `remember` shows that a 201-star plugin can reach 51,442 installs once it sits in the right catalog. Directory approval would do more for cogito-mem's adoption than any feature on the gap list. Today that approval is blocked by an invisible character and a missing `--frozen` flag.

On the product side, the lesson from rivals is to capture more of what a coding session does, not to add structure. Commands, exit codes and files touched answer the "how did we fix this last time" questions that deja-vu, Mem0 and cognee all target. Knowledge graphs and summaries cost LLM calls, and the controlled evidence does not clearly reward them. On evaluation, cogito-mem should turn its honesty into an asset. That means publishing in the formats others use (LongMemEval-S R@5, AMB-style token and latency fields) and plugging into the public harnesses, so that someone other than the author produces the next number.

## What cogito-mem should improve, in priority order

**P0: this week (unblock the directory)**

1. **[Listing] Make the plugin pass directory validation.**
   - Change `displayName` to plain text without U+FE0F.
   - Add `--frozen` to `uv run`.
   - Launch the MCP server and the hooks by executing the script directly, not through `sh`.
   - Move environment setup out of the scripts that hooks and the MCP server run. For example, do a one-time `uv tool install` at install time and have the launcher only exec the installed binary.
   - Run `claude plugin validate --strict .`.

   *Why:* under the pre-submission checklist the first two items **Block** submission and the next two are **Held** for review ([checklist](https://claude.com/docs/plugins/pre-submission-checklist)). episodic-memory already launches with the preferred plain form `node ${CLAUDE_PLUGIN_ROOT}/…` ([plugin.json](https://github.com/obra/episodic-memory/blob/main/.claude-plugin/plugin.json)).
2. **[Listing] Settle the name, complete the listing metadata, then submit to Anthropic's directory** from the account that should own the listing long term.
   - Add `icon`, `documentationUrl` (docs site), `supportUrl` (issues) and `privacyPolicyUrl` (a short "nothing leaves your machine" page).
   - Give the marketplace entry `category: "productivity"`.
   - Name the hosts for the llama.cpp and model downloads in the README.

   *Why:* `remember`, the only memory plugin in the official marketplace, has 51,442 installs on 201 stars and sets `documentationUrl`, `supportUrl` and `privacyPolicyUrl` ([remember plugin.json](https://github.com/Digital-Process-Tools/claude-remember/blob/main/.claude-plugin/plugin.json)). The directory is the only open route ([Publish to the directory](https://claude.com/docs/directory/publish)). The `name` is immutable, and a `cognito` memory plugin already exists in the community catalog.
3. **[Listing] Fix the GitHub front door.**
   - Use a Claude Code–specific description: "Local long-term memory plugin for Claude Code: captures every session, recalls relevant past work. No API key; nothing leaves your machine."
   - Add the topics `claude-code`, `claude-code-plugin`, `mcp-server`, `agent-memory`, `ai-memory`, `long-term-memory`, `local-first`, `llama-cpp`.
   - Put the one-command install in the README: `claude plugin install cogito-mem --marketplace meridian21lab/cogito-mem`, which needs Claude Code v2.1.292+ ([Publish](https://code.claude.com/docs/en/plugins/publish)).
   - Tell users how to enable auto-update for this marketplace.

   *Why:* the repo has 0 topics and a generic description. claude-mem's topics capture "alternative to X" searches. Third-party marketplaces do not auto-update by default.

**P1: next 2–4 weeks (findability, evidence, coding recall)**

4. **[Listing] Publish `cogito-mem` on PyPI and in the MCP Registry.**
   - Add the README marker `<!-- mcp-name: io.github.meridian21lab/cogito-mem -->`.
   - Add the OCI label `io.modelcontextprotocol.server.name` to the GHCR image.
   - Write a `server.json` that lists both packages.

   *Why:* the registry feeds downstream aggregators. mem0 and Letta are there and cognee and claude-mem are not, and the PyPI name is still free ([registry](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/about.mdx); [package-types](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx)).
5. **[Eval] Publish LongMemEval-S results.** Report session R@5 and R@10 on a stated split (all 500 or the cleaned set), with no LLM involved, plus QA accuracy with the official `evaluate_qa.py` gpt-4o judge. *Why:* this is the metric every local peer publishes: deja-vu 97.2, MemPalace 96.6, iai 96.2, agentmemory 95.2, all [self]. QA accuracy puts cogito-mem next to Zep and Supermemory: Zep scored 63.8% with gpt-4o-mini in its January 2025 paper, and Supermemory 81.6% with gpt-4o, both [self] ([LongMemEval](https://github.com/xiaowu0162/LongMemEval); [Zep paper](https://arxiv.org/abs/2501.13956); [AMB external_results](https://github.com/vectorize-io/agent-memory-benchmark/blob/main/external_results.json)).
6. **[Eval] Harden the LoCoMo result.**
   - Repeat judge runs and report mean ± std.
   - Add Wilson 95% intervals per category.
   - Rescore with corrected gold answers using the audit's error list.
   - Run full context on all 1,540 questions, not 762.
   - Map category labels to the Mem0 paper's.
   - Report ingestion wall-clock and context tokens in AMB's field format.

   *Why:* the 3.6-point gap in the full-context control is the obvious objection. "Only Mem0 documents a multi-run methodology". And 56% of adjacent per-category comparisons are statistically indistinguishable ([locomo-audit](https://github.com/dial481/locomo-audit)).
7. **[Function] Capture a compact, redacted record of what the session did.** Store each command with its exit status and the paths of files read or edited, but not full tool output. Make it a setting, so the "words only" default can stay. *Why:* deja-vu (`fix`, `how`, `blame`), the Mem0 plugin (changed files, failed commands), cognee, claude-mem and agentmemory all capture this, and it is the biggest functional gap for coding recall ([deja-vu](https://github.com/vshulcz/deja-vu); [Mem0 plugin](https://github.com/mem0ai/mem0/blob/main/integrations/claude-code-plugin/README.md)).
8. **[Function] Add a small read-only inspector and an opt-out marker.**
   - The inspector is a local page or `cogito-mem` subcommand showing what was stored and what each prompt received.
   - The marker is a `<private>`-style tag or a pause command.

   *Why:* claude-mem, agentmemory, deja-vu, engram and iai all ship viewers, and Supermemory shows a "recall strip". claude-mem, episodic-memory and Mem0 offer exclusion or pause. Output must be escaped, since projectmem shipped a stored XSS in its viewer ([projectmem](https://github.com/riponcm/projectmem)).
9. **[Listing] Convert visitors.**
   - Put a 10–20 s demo GIF at the top of the README.
   - Add a "why local" section with a comparison table against claude-mem, Mem0, cognee and Supermemory, covering LLM calls on write, API key, where data goes and freshness.
   - Open a Docker MCP Catalog PR.
   - Get a Glama listing, then open an awesome-mcp-servers PR.
   - Once the directory or PyPI release is live, launch on Show HN, r/ClaudeAI and r/LocalLLaMA.

   *Why:* claude-mem's README pattern (GIF, badges, one-liners) goes with the top of the market. The Docker catalog's memory shelf holds only `memory`, `neo4j-memory` and a `basic-memory` image last updated 2 May 2025. 282 of the 346 memory entries in awesome-mcp-servers carry Glama badges.

**P2: after traction (depth and reach)**

10. **[Eval] Run SDEBench through AMB's generic "provided" arm**, and contribute retrieval adapters to AMB and OmniMemEval. *Why:* Hindsight is the only plugin with evidence that memory helps a coding agent: fewer interventions and about $0.10 less per task ([AMB sdebench](https://github.com/vectorize-io/agent-memory-benchmark/tree/main/outputs/sdebench)). An adapter also lets someone other than cogito-mem produce its numbers.
11. **[Eval] Add PrecisionMemBench in retrieval mode and BEAM 1M/10M.** *Why:* PrecisionMemBench is judge-free and tests precision, which coverage misses. Hindsight scores 0.857 there [self] and Mem0 and Zep 0.117 [third-party, unverified] ([AMB external_results](https://github.com/vectorize-io/agent-memory-benchmark/blob/main/external_results.json)). BEAM-10M would pair the 26 ms at 10M tokens with an accuracy number at that scale; Mem0 reports 48.6 [self] and Hindsight 64.08 [self].
12. **[Function] Sync across machines and support more agents.** Sync could be export/import, `ssh` or git over the append-only log; capture could extend to Cursor, OpenCode and Gemini CLI. *Why:* deja-vu (`sync ssh`, 42 agents), engram (Git Sync) and claude-mem (cloud sync, 7+ harnesses) cover these. An append-only log makes merge-free sync tractable.
13. **[Function] Decide on reach beyond Claude Code.** Either document a self-hosted, authenticated HTTP MCP deployment of the existing Docker image for claude.ai and Cowork, or state "local only" as a deliberate boundary. *Why:* Supermemory, Honcho and Zep offer hosted MCP endpoints, and the Mem0 plugin works in Cowork. cogito-mem currently cannot serve cloud sessions or claude.ai.
14. **[Listing] Apply to awesome-claude-code at 100 stars** (old enough from about 1 Nov 2026; web issue form only, no emojis), and **pursue the official marketplace** through a partner contact, using the directory Usage numbers as evidence. *Why:* these are the hard gates ([CONTRIBUTING](https://github.com/hesreallyhim/awesome-claude-code/blob/main/CONTRIBUTING.md); [Publish](https://code.claude.com/docs/en/plugins/publish)).
15. **[Function] Keep knowledge graphs, summaries and LLM consolidation as explicit non-goals for now.** *Why:* they reintroduce the LLM costs that drive the top complaints against claude-mem (#3848, #2315, #4847) and episodic-memory (#188). In controlled tests, verbatim retrieval roughly matched full context ([MemDelta](https://arxiv.org/abs/2606.29914)), and hippo-memory's own consolidation lowered recall ([hippo-memory](https://github.com/kitfunso/hippo-memory)). Spend the effort on retrieval quality and coverage instead.
