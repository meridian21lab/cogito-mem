# cogito-mem: requirements and decisions for v0

**Status:** agreed with the author on 2026-10-18 in a question-by-question review. The questions and
answers are in §11. Defaults I chose while writing this file, which still need the author's yes, are
in §12. Evidence: [`literature/memory_api_notation_and_digests.md`](literature/memory_api_notation_and_digests.md)
(API names, checkers, benchmarks) and [`literature/agent_memory_systems.md`](literature/agent_memory_systems.md)
(survey). The earlier design pages in [`notes/`](notes/) are background; where they disagree with this file,
this file wins.

**Built (2026-10-18):** v0 as specified here, in `src/cogito_mem/`, with the tests in `tests/`. Choices made
while building, which still need the author's yes, are in §15. Stage 0 has not been run yet.

**Product focus (added 2026-10-18, after the review):** chats with Claude, Codex and ChatGPT; MCP in v0; setup
in one command; no competing on benchmark numbers. See §1.1, §3.5 and decisions 14–18 in §11.

## 1. What we are building

A memory that runs on the user's own machine. Any agent, or several agents, can **append** text to it and
**query** it, using one fixed JSON shape.

- **Shared memory.** Several agents read and write the same memory.
- **Never forgets.** It only appends. A deletion is a later append that withdraws an earlier item.
- **Keeps time.** It records when each item happened and when it was stored. A query can be asked as of any
  past moment.
- **Fewer tokens to read.** It answers a query with the few stored messages that hold the answer, within a
  token budget the agent sets.
- **Fast and local.** It is built on a frozen open embedding model (EmbeddingGemma 2) running in llama.cpp on
  a CPU. A GPU only makes it faster.

**v0 stores and retrieves messages only.** Digests and rewritten statements come later (§9).

**The end goal.** Agents post whole texts, such as a 10-page report or a long chat, to a shared board. The
memory keeps the main points and the surprising facts without inventing anything, and any agent can query it.

### 1.1 Who it is for and what wins

**Who.** Developers and everyday users of chat assistants: Claude (Claude Code, Claude Desktop, claude.ai),
OpenAI Codex and ChatGPT.

**The job.** Keep the facts of what the user worked on as they go, so nothing is lost because nobody wrote it
down. The case it must handle: a week after a session, the user asks *"Do you remember that idea from a week
ago? I'd like to revisit it"*, and the assistant finds it with one memory query.

**What wins is ease, not numbers.**
- Connecting through MCP is a must, and it ships in v0 (§3.5).
- Setup is one command with nothing to configure: no account, no API key, no config file.
- The API stays as small as it is: two operations, append and query.
- The tests in §5 and §6 stay as our internal checks on quality and speed. We do not chase answer-accuracy
  leaderboards or sell the product on them.

**Later:** images and other media from chats (§9).

## 2. Principles

1. **Static keys.** Every request and response has the same keys every time, and no key ever carries content.
   Optional request keys may be left out, and the server fills in their defaults. Responses always carry
   every key, with `null` when a value is empty.
2. **The query only retrieves.** Everything the memory returns was stored by an append. Nothing is generated
   at query time.
3. **Append-only.** Stored text is never edited. Withdrawals and, later, digests are new items that point
   at what they derive from.
4. **Local-first.** Every memory lives in a folder on the user's machine. Nothing leaves it.
5. **Use the names the industry already uses** (§3.4), unless a plainer word is clearer.
6. **Simple enough to understand in five seconds:** you put items in, and you get items out.
7. **Zero setup.** One command connects the memory to a chat client. Everything else has a working default.

## 3. API v0

**Transport:**
- `POST /v1/memory` on localhost, with a JSON body that names the operation in `op`.
- The Python library takes the same dictionary.
- MCP (v0) exposes the same two bodies as the tools `memory_append` and `memory_query` (§3.5).

### 3.1 append

```json
{
  "op": "append",
  "namespace": "acme-agents",
  "import": false,
  "items": [
    {
      "thread_id": "merger-x",
      "author": "planning-agent",
      "valid_at": "2026-10-14T16:00:00Z",
      "title": "Jana's report on merger X",
      "text": "…the whole message or document…",
      "client_ref": "jana-report-v1",
      "retracts": []
    }
  ]
}
```

| Key | Required | Meaning |
|---|---|---|
| `namespace` | no (default: the memory's saved name, else `"default"`; §15 item 23) | One memory. Every namespace is its own folder on disk. |
| `import` | no (default `false`) | Loading history that was recorded elsewhere. When true, each item's `created_at` is set to its `valid_at`, so `as_of` treats it as if the memory had been running at the time. `valid_at` is then required and must not decrease. |
| `items[].thread_id` | no (default `"default"`) | The conversation, session or thread. A query can filter on it exactly. |
| `items[].author` | yes | Who wrote the item: `"user"`, `"assistant"` or an agent's name. |
| `items[].valid_at` | no (default `created_at`) | When it was said or happened, in RFC 3339. |
| `items[].title` | no | Goes into EmbeddingGemma's title slot. It is returned in `source.title`. |
| `items[].text` | yes | The text, stored word for word. |
| `items[].client_ref` | no | The caller's own id for the item. Resending the same (`namespace`, `author`, `client_ref`) does nothing and returns the original id, so an agent can resend a whole chat and only the new messages are added. |
| `items[].retracts` | no | Ids of earlier items that this item withdraws, from its own `created_at` onward. The text of this item is the reason. |

The response comes back after the item is written to the log and the keyword index. Embedding happens in the
background, so new text can be found by keyword at once and by meaning a moment later (§7 measures the delay).

```json
{
  "items": [
    { "id": "0192f3a1-7c2e-7d10-9b1a-5e2f0c8a4d31",
      "created_at": "2026-10-15T09:12:00.031Z",
      "status": "added",
      "pieces": 22 }
  ],
  "took_ms": 3
}
```

- `status` is `"added"` or `"duplicate"`.
- `pieces` is the number of stored items the text was split into (§4).

### 3.2 query

```json
{
  "op": "query",
  "namespace": "acme-agents",
  "text": "What are the main facts from Jana's report?",
  "context": "Planning the next merger with X",
  "filter": {
    "thread_id": null, "author": null, "kind": null,
    "valid_after": null, "valid_before": null,
    "include_retracted": false
  },
  "as_of": null,
  "top_k": 10,
  "max_tokens": 1000
}
```

| Key | Required | Meaning |
|---|---|---|
| `text` | yes | The question or search text. |
| `context` | no | Extra text that steers the search: in v0 it is joined to `text` before embedding. It is never returned. The pass mark does not measure it (§13). |
| `filter.*` | no | Exact filters. `null` means no filter. `kind` takes a list of kinds. `valid_after` is inclusive and `valid_before` exclusive; both apply to `valid_at`. |
| `as_of` | no (default now) | The moment the memory is viewed from. Only items with `created_at` ≤ `as_of` are visible, and only retractions made by then apply. |
| `top_k` | no (default 10, max 100) | The most items to return. |
| `max_tokens` | no (default 1000; 300 in the first draft, see §15 item 21) | The reading budget: the most tokens of returned `text`, counted with the EmbeddingGemma 2 tokenizer. |

**How items are filled.** Items are taken in score order. An item that would push the total past
`max_tokens` is skipped. The top item is always returned; if it alone is too long, it is cut to
`max_tokens` and its `source.end` is moved to match.

```json
{
  "items": [
    { "id": "0192f3a1-7c2e-7d10-9b1a-5e2f0c8a4d3e",
      "kind": "piece",
      "text": "Integration costs are 40 % above plan.",
      "score": 0.91,
      "similarity": 0.83,
      "author": "planning-agent",
      "thread_id": "merger-x",
      "valid_at": "2026-10-14T16:00:00Z",
      "created_at": "2026-10-15T09:12:00.031Z",
      "expired_at": null,
      "source": { "id": "0192f3a1-7c2e-7d10-9b1a-5e2f0c8a4d31",
                  "title": "Jana's report on merger X",
                  "start": 1840, "end": 1878 } }
  ],
  "as_of": "2026-10-15T09:12:00Z",
  "tokens": 11,
  "took_ms": 38
}
```

- **`kind`:** in v0 this is `"message"` (a whole message) or `"piece"` (one part of a message split under §4).
  `"digest"` is reserved for v1 and `"statement"` for v2.
- **`score`:** between 0 and 1, higher is better. In v0 it is a rank score that can only be compared within
  one response. If stage 1 ships a head, it becomes the estimated probability that the item holds the answer.
- **`similarity`:** the cosine similarity between the query's vector and the item's stored vector (§4), between
  −1 and 1. It does not depend on the other items, so it can be compared across queries, but with EmbeddingGemma 2
  unrelated text often reaches 0.6 to 0.77 (§15). It is `null` when the item has no vector yet (it was just
  added) or the query was not embedded (keyword search, or no embedding model).
- **`source`:** the original message the item came from. `start` and `end` are character positions in that
  message (W3C `TextPositionSelector`: code points, with `end` exclusive), so any agent can check the text.
- **`expired_at`:** the time the item was retracted. It is set only when `include_retracted` is true.

### 3.3 Errors

The service returns the matching HTTP status with the body `{"error": {"code": "invalid_argument", "message": "…"}}`.
The codes are the gRPC / Google AIP-193 names.

### 3.4 Where the names come from

The comparison is in §1 of [`literature/memory_api_notation_and_digests.md`](literature/memory_api_notation_and_digests.md).

| Our key | Source |
|---|---|
| `id`, `text`, `created_at`, `score`, `top_k`, `namespace` | The names most memory APIs and vector databases use (Mem0, Zep, OpenAI, AWS AgentCore, LangGraph, Pinecone). |
| `valid_at` next to `created_at`, and `expired_at` | Zep / Graphiti. Zep and AWS are the only memory APIs that keep both the time something happened and the time it was stored. |
| `as_of` | SQL:2011 `FOR SYSTEM_TIME AS OF`. |
| `source.start` / `source.end` | W3C Web Annotation `TextPositionSelector`. No memory product returns spans. |
| `thread_id` | OpenAI and LangGraph threads. The OpenTelemetry equivalent is `gen_ai.conversation.id`. |
| `author` | Plain word, chosen over the majority `agent_id` / `user_id`, because both people and agents write. |
| `client_ref` | Plays the part of AWS `clientToken` and CloudEvents' rule that `source` + `id` is unique. |
| Ids | UUIDv7, so ids sort by time and the log order is the id order. |

### 3.5 MCP, capture and setup

**Setup in one command.** For example:

```
uvx cogito-mem install claude-code      # or: codex, claude-desktop
```

This one command:
- registers the MCP server with the client (local, over stdio);
- turns on automatic capture where the client has hooks;
- downloads the EmbeddingGemma 2 GGUF on first run;
- creates the memory folder `~/.cogito-mem/` with one namespace, named `<username>-hollow` unless the user
  chooses another name (§15 item 23).

`cogito-mem uninstall <client>` undoes it. The package runner (uvx, pipx or similar) is chosen when we build.

**MCP tools.** They take the same bodies as §3.1 and §3.2, but each tool's schema shows only the keys an
assistant needs. Every other key takes its default.

| Tool | Keys the assistant sees | Filled in by the server |
|---|---|---|
| `memory_append` | `text`, and optionally `title` | `author` from the MCP client's name; `thread_id` from the session, when the client gives one; `valid_at` = now |
| `memory_query` | `text`, and optionally `valid_after`, `valid_before` and `max_tokens` | Everything else, as in §3.2 |

- The response is exactly the §3.2 response. Each item's `valid_at` lets the assistant say when something was
  said.
- The tool description tells the assistant to turn phrases like "a week ago" into `valid_after` and
  `valid_before`.
- The server's instructions tell the assistant two things:
  - search the memory when the user refers to earlier work or asks whether it remembers something;
  - save ideas, decisions, open questions and facts the user states.

**Capture as you go.**

| Client | How chats get in | In v0 |
|---|---|---|
| Claude Code | A hook appends the new messages from the session transcript after each turn or at the end of the session. `client_ref` is the message id, so sending a message again changes nothing. | yes |
| Codex CLI | The same, from the session files Codex writes on disk (the mechanism is to be checked). | yes |
| Claude Desktop | No transcript hook: the assistant saves through `memory_append`, guided by the server's instructions. | yes |
| claude.ai and ChatGPT on the web | They reach only remote MCP servers, not localhost (§13). In v0, past chats come in from the app's data export with `import: true`. | export only |

Captured Claude Code items carry their project (the session's working directory; a Claude Code worktree counts as
its repository) as `title`.

**Recall as you go (Claude Code).** With many MCP servers, Claude Code keeps MCP tools behind tool search, and
Claude rarely calls `memory_query` unprompted. Two more hooks, `cogito-mem recall claude-code`, bring the memory to
Claude instead:
- `UserPromptSubmit`: the memory is queried with the prompt; items that score at least 0.6, share half of the
  prompt's content words (at least 2, at most 4) and are not from the current session come back within 300
  tokens, the current project's first, each with its date and author.
- `SessionStart` (startup and resume): the last three exchanges (each prompt with the final reply to it) of the
  most recent earlier session in the same project, from its transcript.

Both add nothing on an error or after about a second, so they never hold up a prompt. `COGITO_MEM_RECALL=off`, or
`cogito-mem install claude-code --no-recall`, turns them off.

**Acceptance tests.** These are pass or fail, not scores.
1. **Setup.** On a clean machine, one command takes the user from nothing to a first query answered inside
   Claude Code, with no manual edits.
2. **"A week ago."** A scripted session holds an idea in passing, followed by a week of unrelated sessions.
   Asked "Do you remember that idea from a week ago?", the assistant finds it with one `memory_query`, and the
   returned item points to the original message.

## 4. Data model and pipeline (v0, untrained)

**Unit.** One stored item is one message. A message longer than 256 tokens is split at paragraph breaks, then
at sentence breaks if a paragraph is still longer than 256 tokens. Each part is a `piece` that points to its
message.

**Times.**
- `created_at` is set by the memory: UTC with millisecond precision, strictly increasing within a namespace.
  The exception is `import`, where `created_at` = `valid_at`.
- `valid_at` comes from the caller.
- `as_of` filters on `created_at`; `valid_after` and `valid_before` filter on `valid_at`.

**Append path.**
1. Write the text and its metadata to the namespace's append-only log, which is the source of truth.
2. Add the text to the keyword index (BM25).
3. Return.
4. In the background, embed each item with EmbeddingGemma 2 in llama.cpp, using the document prompt
   `title: {title|none} | text: {text}`.
5. Cut each vector to its first 256 numbers (the model is trained for this), normalise it and store it in
   16 bits. Stored vectors are never quantized further.

**Query path.**
1. Embed `task: search result | query: {text}`, with `context` joined in if given.
2. Mask the store to what `as_of` and the filters allow.
3. Run an exact cosine search over the vectors, plus BM25 if stage 0 keeps it, and fuse the two by
   reciprocal rank.
4. Take the top 30 candidates. In stage 0 the reranker may reorder them, and in stage 1 the head.
5. Fill items up to `top_k` and `max_tokens` (§3.2).

**Storage.**
- One folder per namespace.
- The log is append-only, and every index can be rebuilt from it.
- The exact format (SQLite or our own log files with indexes held in memory) is chosen in stage 0 by
  measurement.

## 5. Quality test (the pass mark)

**Dataset.** The long version of LongMemEval (`longmemeval_m`): 500 questions, each with about 1.5M tokens of
user–assistant chat history across about 500 sessions. Use the latest official release and record its file
hash with every result. We never train on it.

**Loading.**
- Each question gets a fresh namespace.
- All of its history sessions are loaded with `import: true`, in date order.
- Each turn becomes one item:
  - `thread_id` = the session id;
  - `author` = the role;
  - `valid_at` = the session date, plus the turn's index in milliseconds to keep the order.
- Sessions that repeat across questions are embedded once and cached by content hash.

**Querying.** `text` = the question, `as_of` = the question date, no filters, `top_k` = 100,
`max_tokens` ∈ {100, 300, 1000}.

**Main metric, coverage at N tokens.** The share of questions where every evidence turn (`has_answer = true`)
has at least one returned item inside the first N returned tokens. The gate uses N = 300; 100 and 1000 are
reported too.

**Scope and reporting.**
- The 30 abstention questions are left out, which leaves 470.
- Report the share of evidence turns that were split into pieces.
- Also report turn-level Recall@5 and Recall@10, which ignore the token budget, so the numbers can be compared
  with the LongMemEval paper.

**Comparisons.** Arms are compared on the same 470 questions, with the paired difference and a 95 % bootstrap
interval. A difference counts only if it is 5 points or more, because 470 questions cannot resolve smaller
gaps.

**Build check.** Before anything else, compare our untrained Recall@5 and @10 with the LongMemEval paper's
plain turn-level retrieval for an embedding model of comparable size, with no query expansion. Write that row
of the paper into this file before running. If we are more than 5 points below it, the gap is a bug in our
build, and we fix it first.

**Same weights as shipped.** Quality is measured with the same GGUF file and runtime that ship, on a
Polonez GPU running llama.cpp with CUDA. This avoids a mismatch between what we test and what we ship.

**Record with every result:** the dataset hash, the GGUF file name and quantization, the commit, the machine,
and the date and time in UTC.

## 6. Speed test

| | Pass mark | Reference | Stretch |
|---|---|---|---|
| Machine | the author's M5 laptop, CPU only (llama.cpp with GPU layers = 0) | Polonez CPU, 8 threads | — |
| Memory size | 10M tokens | 10M tokens | 100M tokens on both |
| Gate | slowest 1 in 20 queries (p95) ≤ 100 ms | reported, used to compare versions | p95 ≤ 100 ms |

**How it is measured.**
- **What is timed:** from the parsed request to the serialised response, inside the warm service process, one
  query at a time, over at least 1,000 queries. The localhost HTTP round trip is reported separately.
- **Reported:** the median, p95 and the maximum.
- **GPU numbers** (Metal on the laptop, CUDA on Polonez) are reported as a bonus and are not a gate.
- **Memory contents:** LongMemEval sessions, deduplicated and concatenated up to the size. The file list is
  recorded.

**Append** has no gate in v0. Two things are reported:
- how long the call takes for messages of 512, 1k, 2k, 4k and 8k tokens (target: under 50 ms, since embedding
  runs in the background);
- how long until new text can be found by meaning.

A timing test on the laptop is a test of the device the memory will run on. Quality conclusions still come
only from the servers.

## 7. Stages, arms and stop rules

### Stage 0: build and measure, no training

| Arm | What it is |
|---|---|
| U1 | Vectors only; each message embedded on its own. |
| U2 | Vectors plus keyword search, fused; each message embedded on its own. |
| U3 | The better of U1 and U2, with each message embedded together with the message before it in the thread. Whether the earlier text is simply prepended or only the message's own tokens are averaged (late chunking) is decided by what llama.cpp exposes. |
| R | The best of U1–U3, plus an off-the-shelf reranker of at most 0.6B reordering the top 30. It is Qwen3-Reranker-0.6B unless a better small one exists on the day; that is fixed before the run. |

**The untrained memory** is the best of U1–U3 at N = 300. Choosing it on the test set favours the baseline, so
it makes the later gates harder, not easier.

**Cost:**
- about 3 GPU-hours to embed the test histories (an upper bound, before deduplication);
- about 1 GPU-hour for the reranker;
- about 1 hour of timing on each machine.

**Decision after stage 0, at N = 300:**
- **R beats the untrained memory by 5 points or more:** go to stage 1. On a machine with a GPU, R itself is an
  option if it meets 100 ms there.
- **Less than 5 points, including an unclear 2–4 point gain:** train nothing. Ship the untrained memory.

### Stage 1: a trained head (only if stage 0 says so)

**Data.**
- Real chats from WildChat (about 1M user–assistant conversations). Check its licence before use, since this
  repository is MIT.
- Multi-session histories are built by grouping conversations under the dataset's anonymised user id, where it
  exists.
- A local open model on Polonez writes about 20k questions, each answered by exactly one turn.
- A question is kept only if its answer appears word for word in that turn and in no other turn of the same
  history.
- Any conversation that shares a 13-word run with a LongMemEval session is removed.
- The questions are split into training and development sets; the development set is used for early stopping
  and calibration.

**Teacher.** The stage-0 reranker's scores on the top 30 candidates.

**Head.**
- It reads only frozen EmbeddingGemma 2 outputs: question and candidate vectors, and token-level outputs if
  they fit.
- It is trained to match the teacher's ranking and the word-for-word labels.
- It must score 30 candidates in at most 5 ms on the laptop CPU.
- Its size is free within that budget.

**Gate: one test run on LongMemEval, at N = 300.**
- It must beat the untrained memory by at least 5 points.
- It must be no more than 2 points below R.
- It must have p95 ≤ 100 ms on the laptop CPU at 10M tokens.

**If it fails:** ship the untrained memory, plus R on GPU, and stop this line. Fine-tuning EmbeddingGemma
itself is the next lever, and it is considered only then.

**Cost:** about 1 GPU-day to write the questions (estimate), minutes to train, and about 1 hour to test.

### Working rules (carried over from MrCogito)

- Quality runs happen on Odra or Polonez. The laptop is for pipeline checks and the on-device speed test.
- Code reaches the servers through git only (push, then pull on the server), never by copying files.
- Polonez runs in bursts under 10 hours, with a 20-minute cooldown after every 5–6 hours. Check that Odra is
  under 80 °C before starting.
- Stop our own processes by PID only, never by pattern.

## 8. What v0 leaves out

These are not part of v0:
- digests and rewritten statements;
- sentence-level trimming inside a message;
- a live connection to claude.ai and ChatGPT on the web, which needs a remote endpoint (§13);
- images and other media;
- network sync between machines;
- a scheduled compaction pass;
- fine-tuning EmbeddingGemma;
- any generated text.

## 9. Roadmap after v0

| Version | What | Test it must pass |
|---|---|---|
| v1: digest | On append of a long text, and when a chat session ends, store the text's own sentences as `kind: "digest"`, with their source spans and with the title and author for context. The digest takes the sentences closest to the text's overall meaning (its main points) and those least like anything already in memory (the surprising ones). | **A planted-fact test** we build ourselves, since no public benchmark scores surprise. Long texts get planted main points that repeat across the text, and planted surprising facts that contradict what the memory already holds. The score is the share of planted facts kept within a fixed digest length, plus a set of broad questions ("main points of X"). |
| v2: statements | A model under 3B writes short, checked statements. A terse, ungrammatical "caveman" style is fine, because the statements are for agent-to-agent use. Every statement is checked by a small fact-checker against its source span, and statements that fail are dropped. Stored as `kind: "statement"`. | It must beat v1 copying on the planted-fact test at the same token count, with a measured rate of invented content. For reference, small summarizers of 4B invent something in about 6 % of summaries. |
| Later: media | Images, screenshots and files shared in chats, found by a text query. The model is open. | Its own pass mark before it ships. |
| Later | Live connection to claude.ai and ChatGPT on the web; sync between machines (replicating the append-only log); a scheduled job that runs the v1 and v2 writers and appends their output; sentence-level trimming scored on questions whose answer appears word for word; fine-tuning EmbeddingGemma only if the stage-1 head stops improving. | Each gets its own pass mark before it ships. |

## 10. The original requirements (17 Oct) and where they stand

| # | Requirement | Status in v0 |
|---|---|---|
| 1 | Encode facts quickly | EmbeddingGemma 2 in llama.cpp, with embedding in the background. Append speed is reported (§6). |
| 2 | Usable by any decoder, through text or JSON | Yes. Every returned item is plain stored text. |
| 3 | Compress | Redefined as fewer tokens for the agent to read: coverage at N tokens (§5). Stored vectors are 256 numbers in 16 bits and are not quantized further. |
| 4 | Time and order; never forget; mark as deleted | `created_at`, `valid_at`, `as_of`, `retracts`, `expired_at`. |
| 5 | Extends like a tape | An append-only log per namespace; ids sort by time. |
| 6 | Scheduled compaction and relinking | Later (§9): the v1 and v2 writers on a schedule, writing through `append`. |
| 7 | Retrieval under 100 ms on CPU or GPU | p95 ≤ 100 ms on the laptop CPU at 10M tokens; 100M is the stretch mark. |
| 8 | Works across the network | v0 is local only (localhost HTTP); sync comes later. |
| 9 | A fixed protocol like Jev's | Fixed JSON with static keys, a score on every item, and no generated text. Unlike Jev, there are no typed questions: a query returns stored items. |

## 11. Decision log (review of 2026-10-18)

| # | Question | Decision | Why |
|---|---|---|---|
| — | API shape | Keys are always static; no key carries content. This corrected the earlier draft, which keyed answers by question name. | The author's requirement. Simple and predictable for any client. |
| 1 | Where does the returned text come from? | It is written at append time; the query only retrieves. | Generating at query time breaks 100 ms, and nothing checks the output before an agent reads it. |
| 2 | Who writes the digest? | Copying first. Later, a model under 3B writing short checked statements for agent-to-agent use. | Copying cannot invent facts and needs only EmbeddingGemma. Rewriting has to earn its 2–7 s and its roughly 6 % rate of invented content. |
| 3 | What does the query's time mean? | `as_of`: a viewpoint that defaults to now. Windows on when things happened are optional filters. | One meaning per field. It also allows replays, debugging, and dated benchmark questions. |
| 4 | What should compression measure? | Tokens the agent has to read. | The vectors are already about half the size of the text, which we keep word for word, and search speed can be fixed without training. Reading is the agent's real cost. |
| 5 | Which test decides? | LongMemEval, long version, for general long user–assistant chats. | The use case is general chat. It also tests time (dated sessions and questions, updates). Research reports were only an example. |
| 6 | What must a trained picker beat? | The untrained memory by at least 5 points, and the off-the-shelf reranker within 100 ms on CPU. | If a free reranker already does the job within budget, training buys nothing. |
| 7 | What does the picker learn from? | Real WildChat chats with generated questions, kept only when the answer appears word for word, and checked for overlap with LongMemEval. | Learn how real people state facts, not one generator's habits, which LongMemEval shares. |
| 8 | Does training change EmbeddingGemma? | No, it stays frozen. | Stored vectors stay valid (re-embedding 100M tokens takes about 25 min on a GPU and about 18 h on a CPU), and only one thing changes. |
| 8b | Should we train anything at all? | Only if the reranker gains 5 points or more and the memory must run on CPU. Then a small head is distilled from it. Fine-tuning the reranker does not help. | The only job training has is bringing reranker quality inside the CPU budget. |
| 9 | CPU or GPU? | A local machine, CPU, with every memory kept local. A GPU only accelerates. llama.cpp or similar. The first version may be slower, but speed matters in the long run. | Memory that plugs into any agent runs beside it, often with no GPU. |
| 10 | Where is the 100 ms measured? | Laptop CPU at 10M tokens (pass mark) and Polonez CPU at 10M tokens (reference), timing the slowest 1 in 20 queries; 100M tokens as the stretch mark. | Two machines make the comparison broader. An average would hide the slow queries agents actually wait on. |
| — | Which model? | EmbeddingGemma 2. Decided from evidence, not asked. | llama.cpp's own team published a build on release day; Apache 2.0; 8k context; 60.4 against 59.7 at 256 numbers. |
| 11 | What is one item? | One message, split at paragraphs when longer than 256 tokens. | The test labels whole messages, so scoring is exact, and a message keeps its own context. |
| — | A message on its own, or with the message before it? | Measured in stage 0 (arm U3). | — |
| 12 | Digest in v0? | No. v1, with a planted-fact test. | The pass mark cannot see a digest, so it would ship untested. |
| 13 | Stages and stop rules | As in §7. An unclear result means train nothing. | Stage 0 alone gives a working local memory and answers whether training is worth anything. |
| 14 | Who is it for? | Developers and users of Claude, Codex and ChatGPT, keeping the facts of what they worked on as they go (§1.1). | The author, after the competitive review. The case: getting back an idea from a week ago that nobody wrote down. |
| 15 | MCP in v0? | Yes, a must (§3.5). | It is how these clients connect to tools. |
| 16 | How hard is setup? | One command, no configuration, no account and no key. | Ease is the product. |
| 17 | Compete on benchmark numbers? | No. §5 and §6 remain internal checks. We do not chase answer-accuracy leaderboards. | The author does not want a numbers game; the product is simplicity. |
| 18 | Images and other media? | Later (§9). | Text first. |

## 12. Defaults chosen while writing (author to confirm)

1. **`import` flag.** Without it, loading old history would stamp every item with today's `created_at`, and
   `as_of` set to a past date would see nothing. Mem0 has the same idea: its `timestamp` backdates
   `created_at`.
2. **`client_ref` for deduplication,** so an agent can resend a whole chat.
3. **"Matching the reranker" means no more than 2 points below it** at N = 300.
4. **The fill rule:** skip an item that does not fit the budget; always return the top item, cut if needed.
5. **The append call returns before embedding finishes,** with keyword search available at once.
6. **Quality is measured with the same GGUF file that ships,** not with PyTorch weights.
7. **`context` is joined to `text` before embedding** in v0.
8. **The setup command and folder:** `uvx cogito-mem install <client>`, with every memory under
   `~/.cogito-mem/` (§3.5).
9. **MCP fills in `author`** from the client's name and shows the assistant only the keys it needs (§3.5).

## 13. Open questions

- **Score and abstention.** Should the memory say "nothing relevant" (return no items) below some score?
  LongMemEval's 30 abstention questions could test this once the score is calibrated.
- **`context`.** The pass mark gives no context, so this field is untested. It needs its own small test before
  it can claim to help.
- **Storage format.** Chosen in stage 0 by measurement (§4).
- **Many agents appending at once.** Order is the server's arrival order. Is that enough?
- **Retraction rights.** Who may retract whose items, and should retracted text ever be returned by default?
- **Names.** `author` and `thread_id` against the majority `agent_id` / `user_id` and `session_id`. Revisit if
  MCP clients expect the others.
- **WildChat licence** for a head shipped in an MIT repository (stage 1).
- **claude.ai and ChatGPT on the web.** They reach only remote MCP servers. Do we offer a tunnel or a hosted
  relay, given that local-first is a principle? Until then, these chats come in only from exports.
  *Postponed (2026-10-18): the MVP is local, for the author alone. Candidates for later: a Cloudflare quick
  tunnel (no account, but no SSE, so MCP must answer with plain JSON), a named Cloudflare tunnel or Tailscale
  Funnel (a stable address), each with a secret in the URL path.*
- **What automatic capture keeps.** Every turn, or also tool output and code? How do we keep secrets (keys,
  tokens) out of a memory that never forgets?
- **One memory per user or per project?** Claude Code works per project folder. The candidates are one
  namespace for everything with the project as a filter, or one namespace per project.

## 14. Evidence so far

Measured on Polonez on 2026-10-17, between 16:30 and 16:57 UTC, with PyTorch and sentence-transformers:
EmbeddingGemma 2 in bf16 on one RTX 3090, or in fp32 on 8 CPU threads. These are **not** llama.cpp numbers;
stage 0 measures again with the runtime that ships. The script is `scripts/bench_ingest.py` in the MrCogito
repository, at commit c8051d3 on branch `e33-multihop`.

| What | GPU | CPU, 8 threads |
|---|---|---|
| Embed 1M tokens in bulk | 14.3–14.8 s | about 11 min (6.4k characters/s) |
| Append 512 / 1k / 2k / 4k / 8k tokens, in 256-token pieces | 33 / 34 / 44 / 79 / 145 ms | 0.49 / 0.80 / 1.45 / 3.18 / 6.86 s |
| Embed one question | 30 ms | 59 ms |
| Exact search over 625k vectors of 256 numbers | 0.45 ms | 61 ms |
| Write to the log and the keyword index, per append | — | 0.18–0.83 ms |

From these, a whole CPU query at 10M tokens should take about 65 ms, almost all of it embedding the question.
At 100M tokens it took about 120 ms, which is over budget; the fixes are a graph index or a GPU.

## 15. Choices made while building v0 (author to confirm)

These fill gaps the sections above leave open. Each can change without touching the API.

1. **Storage: SQLite.** Each namespace is `~/.cogito-mem/memory/<namespace>/log.sqlite3`, one table that triggers
   keep append-only (any UPDATE or DELETE is refused). The keyword index, the row arrays for filtering and the
   vector matrix are held in memory and rebuilt from the log. Several processes may open one namespace: writes
   take SQLite's lock and reads first pick up rows others added. §4 leaves the format to stage 0; this is the
   baseline that stage 0 measures.
2. **Vectors live in a shared, content-addressed cache** (`~/.cogito-mem/cache/embeddings.sqlite3`, keyed by
   sha256 of model name + prompt). Text seen twice, in any namespace, is embedded once (§5's "embedded once and
   cached by content hash"); deleting the cache only costs re-embedding.
3. **Runtime: llama.cpp's own `llama-server`,** started as a child process, not Python bindings. The bindings
   lag llama.cpp: llama-cpp-python 0.3.36 (2026-10-01) predates EmbeddingGemma 2 (2026-10-06), whose GGUF
   uses the new `gemma-embedding2` architecture. The server also brings Metal and CUDA builds for free. The
   model is `embeddinggemma-2-Q8_0.gguf` (310 MB) from `ggml-org/embeddinggemma-2-GGUF`. A watchdog stops the
   server if the memory process dies.
4. **One warm service.** `cogito-mem serve` holds the memory and the model; the MCP server, the hooks and the
   CLI are thin clients that start it on demand. It listens on 127.0.0.1:7327, stops after one idle hour, and
   refuses requests whose body is not JSON or whose `Host` is not local, so a web page cannot read or write it.
5. **The default `as_of` is the memory's clock:** max(now, the latest `created_at`). `created_at` strictly
   increases by at least 1 ms, so a burst of appends can run a few milliseconds ahead of the wall clock; with
   "now" alone, a query right after such a burst would miss the newest items.
6. **Pieces are packed.** After splitting at paragraph and sentence breaks, neighbouring parts are joined while
   they fit in 256 tokens, so pieces are close to 256 tokens rather than one per paragraph. A sentence longer
   than 256 tokens is cut at token boundaries.
7. **Keyword search:** BM25 over the item's text and its title. Common English function words ("do", "you",
   "that"…) are dropped from the query, not from the index; a query made only of them still matches.
8. **Score:** reciprocal rank fusion (k = 60) of the vector and keyword lists, divided by its maximum, so an item
   ranked first in every list scores 1. With a reranker, the top 30 take the reranker's score.
9. **Arm U3** prepends the message this one follows on from, cut to its last 1,000 characters: the previous
   piece of the same message, or the previous message in the thread **when another author wrote it** (the
   message being replied to). A run of messages by one author, such as notes saved one after another, are
   embedded alone: with the previous note prepended, a set of 9 unrelated notes went from 9/9 to 4/9 found
   by meaning (EmbeddingGemma 300M).
10. **Capture keeps** the user's typed messages and the assistant's text replies, and from Claude Code one item
    by author `actions` per turn (the tool calls between two prompts): the command lines it ran, marked when they
    failed or did not run, and the files it read, edited or wrote, at most 800 characters
    (`COGITO_MEM_CAPTURE_ACTIONS=off` leaves it out). Its `client_ref` is the line of the turn's first tool call,
    so capturing again from any point adds no second copy. It leaves out tool output, file contents, thinking,
    sub-agent turns, slash-command output, injected system reminders, compaction summaries and text inside
    `<private>…</private>`. Obvious secrets (API keys, tokens, private keys, `password=…`) are replaced with
    `[redacted]` before they are stored. Backfills (`capture … --all`, exports) use `import`.
    `COGITO_MEM_CAPTURE=off` pauses the hooks. Recall shows `actions` items after the messages, in the room left.
11. **MCP details:** `author` is the client's name from `initialize`; `thread_id` is the Claude Code session
    (Claude Code passes `CLAUDE_CODE_SESSION_ID` to MCP servers), else `default`. Tool errors come back as tool
    results with `isError`, and every result carries the §3.2 response as text and as `structuredContent`.
12. **Limits:** at most 1,000 items per append and 4M characters per text; `max_tokens` at most 100,000.
    Imports may not be dated more than 5 minutes in the future.
13. **MCP over HTTP.** The service also speaks MCP's Streamable HTTP transport at `/mcp` (JSON responses, a
    session per `initialize`, `?namespace=` to pick the memory), so a client can connect by URL, e.g. to the
    Docker image. It checks `Origin` as well as `Host`.
14. **Distribution.** Four ways in, all ending in the same `~/.cogito-mem`: a one-line installer (`install.sh`,
    `install.ps1`: uv, then `uv tool install`, then `cogito-mem install` for every client found), a Claude Code
    plugin and marketplace in this repository, a Docker image (`Dockerfile`, `compose.yaml`; llama.cpp built
    portable, model downloaded to the volume or baked in), and plain `pip`/`uv`. `cogito-mem doctor` checks an
    install. The service downloads llama.cpp on first start when none is installed.
15. **Prompt profiles.** EmbeddingGemma's prompts stay the default. Other Matryoshka-trained GGUFs
    (Qwen3-Embedding, nomic-embed-text) get their own prompts, chosen from the file name or `COGITO_MEM_PROMPTS`.
    This exists for experiments and for users who prefer another model; v0 ships EmbeddingGemma 2.
16. **The default is now U3 plus the author's name (`doc_context="previous"`, `doc_author=True`),** following
    §7's rule that the untrained memory is the best arm at N = 300, measured on LoCoMo because LongMemEval and
    EmbeddingGemma 2 could not be downloaded in the build environment. **LongMemEval must confirm it in stage
    0.** `doc_author` writes the author's name before the text for embedding and keyword search ("Caroline:
    …"). Paired results on LoCoMo's first 3 conversations (383 questions; Qwen3-Embedding-0.6B at 256
    numbers, since the reachable EmbeddingGemma GGUF lacked its projection, see 17):

    | Arm | Coverage@100 | @300 | @1000 | R@10 |
    |---|---|---|---|---|
    | keyword (BM25) | 32.4 % | 47.3 % | 60.1 % | 51.2 % |
    | keyword + author | 36.3 % | 50.6 % | 61.9 % | 53.0 % |
    | vector, own text (U1) | 7.0 % | 12.8 % | 27.9 % | 13.1 % |
    | hybrid, own text (U2, the earlier default) | 15.9 % | 32.9 % | 57.4 % | 33.2 % |
    | hybrid + previous (U3) | 21.1 % | 40.0 % | 59.8 % | 41.5 % |
    | vector + previous + author | 23.5 % | 39.4 % | 58.8 % | 43.3 % |
    | **hybrid + previous + author (new default)** | 32.6 % | **50.9 %** | **70.8 %** | 52.5 % |
    | the last N tokens of the conversation (no memory) | 0.0 % | 0.8 % | 4.2 % | — |

    On all 10 conversations (1,536 questions) the new default covers 32.0 / 49.4 / 67.8 % at N = 100 / 300 /
    1000, against 32.5 / 46.7 / 57.6 % for keyword search and 0.1 / 0.6 / 4.4 % for the last N tokens
    (+2.7 points over keyword at 300 [0.7, 4.7]; +10.2 at 1000 [8.5, 12.0]).

    With EmbeddingGemma 2 Q8_0, the model that ships (19 Oct 2026, on the author's M5 Max laptop), the new
    default covers 39.0 / 56.5 / 72.5 % on all 10 conversations, against 36.0 / 49.5 / 59.8 % for keyword search
    (+7.0 points at 300 [5.3, 8.8]; +12.7 at 1000 [11.0, 14.5]); R@10 57.2 % against 51.6 %. The other arms in
    the table were not rerun with it.

    Paired differences on the 3 conversations, with 95 % bootstrap intervals: new default vs U2 +18.0 points at N = 300 [13.3, 22.7]
    and +13.3 at N = 1000 [9.7, 17.0]; vs keyword + author +0.3 at 300 [−3.4, 4.2] (no difference) and +8.9 at
    1000 [5.2, 12.5]. Turn by turn, a LoCoMo answer ("Researching adoption agencies") rarely says who is
    speaking or what it answers, so embedding it alone loses both; cutting vectors to 256 numbers was not the
    cause (on 40 questions, R@10 0.57 at 256 numbers against 0.62 at 1,024 with context; 0.10 against 0.07
    without).
17. **Model files must carry the final projection.** EmbeddingGemma's GGUF on Docker Hub (`ai/embeddinggemma`)
    has no dense projection layers, so its 768 numbers are pooled hidden states and cutting them to 256 is not
    what the model was trained for (vector-only coverage on LoCoMo fell to about 20 %). The `ggml-org`
    EmbeddingGemma 2 GGUF we ship includes the projection (`output.weight`); stage 0 should still check the
    shipped file's vectors against the reference implementation once.
18. **BLAS runs on one thread in the service.** The query's one large matrix product is memory-bound, and idle
    BLAS threads spinning on the cores llama-server needs added about 70 ms to each query on a 4-core VM
    (embedding 174 ms → 105 ms median with one BLAS thread).
19. **Speed on the author's laptop** (MacBook Pro, M5 Max, 18 cores, 19 Oct 2026; EmbeddingGemma 2 Q8_0 embeds
    every query; the memory is synthetic text with random vectors): p95 22.8 ms at 1M tokens and 26.0 ms at
    10M tokens with the CPU alone (median 14.5 and 17.8 ms), 14.2 ms at 10M with Metal; 26.1 ms at 10M on the
    CPU over localhost HTTP. §6's gate (p95 ≤ 100 ms at 10M tokens, CPU only) passes, with synthetic text
    standing in for LongMemEval's sessions. Appends at 10M tokens on the CPU: 2.2 / 2.7 / 4.4 / 7.4 / 10.9 ms
    median for 512 / 1k / 2k / 4k / 8k tokens (0.8 / 1.4 / 2.5 / 4.7 / 9.1 ms with Metal), all under the 50 ms
    target; searchable by meaning about 57 ms later on the CPU and 13 ms with Metal (medians of 10). With Metal
    the model embeds about 21k tokens a second (1M tokens in 46.9 s). Earlier, on a 4-core cloud VM (Intel Xeon
    2.8 GHz, CPU only, EmbeddingGemma 300M Q8_0 for the query): p95 140 ms at 1M tokens and 163 ms at 10M, of
    which search and fill took about 3 ms and 28 ms; appends 5 ms (512 tokens), 47 ms (4k), 69 ms (8k, over the
    50 ms target there: the text is tokenized once through llama-server before returning).
20. **Arm R on CPU is far over budget:** Qwen3-Reranker-0.6B in llama.cpp scored 32 candidates in about 16 s on
    the same VM (about 0.5 s each), so R stays a GPU option, as §7 expects. Its scores also looked
    uncalibrated (0.015 for a clear match); check the GGUF's rerank template before using R's scores.
21. **The default budget is 1,000 tokens, not 300** (author's decision, 19 Oct 2026). On LoCoMo answered by
    gpt-4o-mini and judged by an LLM, 300 tokens scored 8.7 points below the whole conversation (−12.5 to −4.7),
    while 1,000 was level with it (−1.8, −5.5 to +1.8), and 1,000 tokens is small next to a chat client's context.
    The pass marks of §13 still name their own budgets.
22. **Recall filters by shared words, not by `similarity`.** On a copy of a real memory (470 messages,
    1,191 items, EmbeddingGemma 2 Q8_0), 18 prompts were run, 9 about the work stored in it and 9 unrelated, and
    each returned item was labelled on topic or not. The closest item scored a similarity of 0.78 to 0.88 for
    the related prompts and 0.65 to 0.77 for the unrelated ones, so a threshold has almost no margin. Item by
    item, score ≥ 0.6 with the word rule kept 43 of 57 on-topic items, 4 off-topic ones and nothing for the
    unrelated prompts. Score ≥ 0.6 with similarity ≥ 0.77, the lowest threshold that keeps nothing for the
    unrelated prompts, kept 42, 9 and nothing. Similarity relative to the prompt's other items (z-score, gap to
    the mean) overlapped too. Allowing either the word rule or similarity ≥ 0.85 kept one more on-topic item and
    no noise, too little to set a threshold on.
23. **The memory is named `<username>-hollow`** (author's decision, 19 Oct 2026), e.g. `ksirg-hollow`: the hollow
    is where Cogi, the squirrel, keeps its nuts. `default` told users nothing about what or whose the memory was.
    The name comes from `COGITO_MEM_NAMESPACE` when it is set and not empty, else from `~/.cogito-mem/config.json`
    (`{"namespace": …}`), else from the username (`getpass.getuser()`, lowercased, characters outside
    `[a-z0-9._-]` replaced by `-`, cut to fit 64; `my-hollow` if nothing is left). The name in use is saved to
    `config.json`, so the CLI, the MCP server and the hooks agree even when only one of them has the variable;
    `--namespace` picks another memory for one command without saving it. A name that breaks the rule (letters,
    digits, `.`, `_`, `-`, up to 64) is an error that says so: on the command line, in the capture hook's output and
    in every MCP tool result; recall then adds nothing and notes why in `run/recall.log`. The Claude Code plugin
    asks for the name when it is enabled (`userConfig.memory_name`, given to the MCP server as
    `COGITO_MEM_NAMESPACE` and to the hooks as `CLAUDE_PLUGIN_OPTION_MEMORY_NAME`, which the plugin's script
    passes on); left empty, Claude Code substitutes an empty string and the saved name or `<username>-hollow`
    applies. `cogito-mem install --name` sets it outside the plugin.

    **Nothing is lost on the way.** The first time a name is saved, a memory from before names (`memory/default`)
    is renamed to it, under a file lock (`run/namespace.lock`), after stopping a local service that holds the folder
    open (the next request starts it again), and with one INFO line. When both folders exist, both are kept and a
    warning is logged; nothing is renamed when the name is `default`. The service does the same at start, but only
    for a name it was given (the variable, e.g. `docker run -e`, or `config.json`), never one derived from its own
    user, which in a container is not the person's. Nothing else is keyed by the name: capture cursors are keyed by
    session or file, and the embedding cache by model and prompt, so a renamed memory keeps both.

    **Requests without `namespace` go to the saved name, or to `default` when none is saved.** The clients always
    send the name, so this only matters to HTTP and Python callers and to MCP over HTTP without `?namespace=`.
    The service reads `config.json` in its own memory folder, which the local clients write, so the README's
    `curl` examples reach the same memory as the assistant. It does not fall back to `<username>-hollow`:
    a service in Docker runs as another user, and would invent a name nobody chose. A Docker service with no name
    given keeps `default`.
