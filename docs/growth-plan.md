# Growth plan: making Cogi the memory people install first

Goal: **the most-installed memory plugin in Claude's plugin directory**, and the one people recommend when someone
asks "how do I make Claude Code remember?". Written 20 Oct 2026 from the competitor research in
[`notes/competitors_20261020.md`](notes/competitors_20261020.md).

## Where we start, and what decides the race

- **Installs come from catalogs, not stars.** `remember`, the only memory plugin in Anthropic's official marketplace,
  has 51,442 installs on 201 GitHub stars; claude-mem has 101,876 stars and no claude.com page. The open route is the
  **directory** (claude.ai/directory/manage). Anthropic decides placement and the *Verified* label during review;
  nobody can buy or apply for them. What we control is quality, a clean review, and usage that grows.
- **Our position is real but invisible.** Cogi is the only well-measured plugin that keeps your exact words, makes
  **no AI calls** to store, needs **no key** and **no cloud**, and recalls a turn the moment it ends. Rivals bill an
  observer model per tool call (claude-mem), need a paid API key (Mem0), or run LLM extraction (cognee, Supermemory).
  Today: 0 stars, no listing anywhere, no PyPI package.
- **The story in one line:** *"Claude forgets. Cogi doesn't. 1,000 tokens from Cogi answer LoCoMo questions as well
  as rereading the whole conversation. Free, local, no API key."*

## Phase 0: be listable (this week)

| # | Task | Who | State |
|---|---|---|---|
| 1 | Plugin passes the directory's pre-submission checklist (`uv run --frozen` launcher, no invisible characters, icon, docs/support/privacy URLs, category) | Claude | done, v0.2.0 on `dev` |
| 2 | Privacy policy page, one-command install, auto-update instructions, README comparison table | Claude | done |
| 3 | `server.json` + release workflow publishing to PyPI and the MCP Registry | Claude | done |
| 4 | Merge `dev` → `main`, then tag `v0.2.0` | you (or ask Claude) | — |
| 5 | On pypi.org: add `meridian21lab/cogito-mem`, workflow `release.yml`, environment `pypi` as a pending trusted publisher of `cogito-mem` (before the tag) | you | — |
| 6 | GitHub repo: description, topics, website, social preview (commands below) | you | — |
| 7 | Make the GHCR package public (Packages → cogito-mem → Change visibility) | you | — |
| 8 | **Submit to the directory** at claude.ai/directory/manage from the account that should own the listing for good (the first organization to submit a repository holds it; the plugin name can't change) | you | — |
| 9 | Record a 20-second demo GIF of the "acorn" test (say it, `/clear`, ask, Cogi answers) | you | — |

Repository settings, from a terminal with the GitHub CLI:

```sh
gh repo edit meridian21lab/cogito-mem \
  --description "Local long-term memory for Claude Code: keeps every session word for word and brings back what Claude forgot. No API key, nothing leaves your machine." \
  --homepage "https://meridian21lab.github.io/cogito-mem/" \
  --add-topic claude-code,claude-code-plugin,claude,mcp,mcp-server,agent-memory,ai-memory,long-term-memory,local-first,llama-cpp,embeddings,privacy
```

Then *Settings → General → Social preview*: upload the Cogi card image from the site's assets folder; and *Settings → General →
Features*: turn on **Discussions**.

## Phase 1: launch (weeks 1–4)

| Week | Moment | Channels |
|---|---|---|
| 1 | Directory submission; v0.2.0 on PyPI and the MCP Registry; soft launch to people who will give honest feedback | LinkedIn post with Cogi; 5 first-user sessions (below) |
| 2 | **Show HN**: "Cogi: local memory for Claude Code, as good as rereading the whole conversation with 5% of the tokens" (post Tue–Thu, 8–10 am US Eastern; stay in the thread all day) | HN, then X thread with the results chart |
| 2 | Reddit, each post written for that community, not cross-posted | r/ClaudeAI (the "it forgot again" pain), r/ClaudeCode, r/LocalLLaMA (local EmbeddingGemma 2, no API) |
| 3 | Listings that feed aggregators | Glama, Smithery, PulseMCP, mcp.so (all read the MCP Registry); PR to awesome-mcp-servers (Knowledge & Memory) |
| 3 | Docker MCP Catalog PR (its memory shelf has only `memory`, `neo4j-memory` and a stale `basic-memory`) | docker/mcp-registry |
| 4 | **awesome-claude-code** (needs ≥ 100 stars and a 14-day-old repo: eligible from about 1 Nov) | issue form, no emoji |

Launch rules: lead with the one-line story and the 20-second GIF; answer every comment within the hour on launch
day; never ask for stars, ask for feedback; every criticism becomes an issue or a docs line within a day.

## The regular machine (every week, every month)

Growth comes from a steady rhythm more than from one launch.

**Every week**

| Day | Ritual | Output |
|---|---|---|
| Mon | **Numbers** (15 min): directory installs and error rate (Usage tab), stars, PyPI downloads (pypistats), MCP Registry and Glama position, new issues | one line in `docs/notes/growth-log.md` |
| Tue | **Release train**: ship what's ready as a new version, even if small; release notes say what Cogi learned this week | a GitHub release; users with auto-update see "Plugin updated" |
| Wed | **One piece of content**, rotating: a benchmark, a how-to ("make Claude remember why you chose X"), an honest comparison, a behind-the-scenes ("how a basket of 1,000 tokens is filled") | a post on the docs site + LinkedIn/X |
| Thu | **Community**: answer every issue and discussion; one helpful reply in r/ClaudeAI or the Claude Discord where someone asks about memory (help first, link only if it answers the question) | — |
| Fri | **One first-user session**: watch someone new install and use Cogi, as on 19 Oct; every question becomes a docs fix | a row in a session note |

**Every month**

- **Benchmarks refreshed** on the results page (LoCoMo, LongMemEval-S recall, speed), dated, with the command to
  reproduce. Add competitors' published numbers with their protocol, honestly.
- **One feature people asked for** (from issues), announced as its own small launch.
- **A neutral "Claude Code memory benchmark" page** that scores every plugin we can run the same way. The page people
  cite becomes the page people link to.
- **Review**: what moved installs, what didn't; drop what doesn't work.

**Every quarter**

- A bigger launch (sync between machines, Cursor/OpenCode capture, a coding-agent benchmark) with a second Show HN.
- Ask Anthropic, through a partner contact, about the official marketplace, with three months of directory usage
  and error rates as evidence.

## Content that compounds

- **Search pages** on the docs site, one question each: "How do I make Claude Code remember past sessions?",
  "claude-mem alternative without observer tokens", "Mem0 for Claude Code without an API key", "Claude Code memory
  benchmarks". Register the site in Google Search Console (a meta tag; no tracking of visitors).
- **The proof**: the LoCoMo chart, the 26 ms at 10M tokens, "0 AI calls to store". Use the same three numbers
  everywhere.
- **Cogi as the face**: the squirrel on every card, GIF and post; a short series "Cogi remembers…" with real recalls
  from real sessions (with permission).
- **Third-party numbers**: contribute retrieval adapters to the Agent Memory Benchmark and OmniMemEval, so people
  other than us publish Cogi's scores.

## Product moves that drive growth

In order (from the competitor research):

1. **Capture what the session did**: commands, failures and files touched (in progress), the biggest gap for coding
   recall.
2. **LongMemEval-S recall** published next to deja-vu, MemPalace and agentmemory (harness in progress; run on the M5).
3. **More agents**: Cursor, OpenCode, Gemini CLI; each one is a new listing and a new announcement.
4. **Sync between machines** over the append-only log (export/import, then ssh or git).
5. **A coding-agent benchmark** (SDEBench through the Agent Memory Benchmark): evidence that memory makes Claude
   finish tasks with fewer interventions.

Keep out: knowledge graphs, summaries and AI consolidation. They bring back the token bills that drive the top
complaints about the rivals.

## Targets

| By | Directory | GitHub stars | Other |
|---|---|---|---|
| 1 Nov 2026 | submitted; v0.2.0 on PyPI and the MCP Registry | 100 | 5 first-user sessions done |
| 1 Dec 2026 | listed; 1,000 installs | 500 | awesome lists, Docker catalog; first third-party benchmark |
| 1 Mar 2027 | 10,000 installs; Verified | 2,000 | top memory result on Glama and the MCP Registry search |
| 2027 | #1 memory plugin by installs (beat `remember`'s 51k) | 5,000+ | official marketplace |

These are ambitious on purpose; the weekly numbers line shows early whether a channel works.
