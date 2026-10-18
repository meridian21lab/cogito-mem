# Agent memory — systems, trained memories, latent channels, retrieval, time and consolidation

Survey written 2026-10-17 for the "memory for agents" direction: a memory that takes 1M–100M
tokens of agent traffic (chats, documents, codebases), compresses it, keeps time order (append
only, never forget, mark as superseded or deleted), is queried by **any** LLM through text/JSON
in under 100 ms, runs a scheduled offline "relink / compact" pass, and works across the network.
The design proposal built on this survey is in
[`../notes/agent_memory_atlas_20261017.html`](../notes/agent_memory_atlas_20261017.html).

> Written in the MrCogito repository on 2026-10-17 and moved here on 2026-10-18. Decisions taken since
> then are in [`../requirements.md`](../requirements.md); where this survey and that file disagree,
> the requirements win.
>
> **Updated 2026-10-18.** The product now targets people's own chats with Claude, Codex and ChatGPT: MCP in
> v0, setup in one command, and no race on benchmark numbers (requirements §1.1, §3.5). Section J covers the
> products that compete directly for that use and where cogito-mem stands against them. The families A–I
> and the closing findings were written for the MrCogito research line (latent memory). cogito-mem v0
> uses none of the latent parts.

Numbers are as reported by each paper or vendor. **[V]** = vendor-reported, not independently
checked. **[abs]** = checked at abstract level only. All star counts read 2026-10-17.

## How to read this file

The field splits into nine families, plus section J on the products that compete directly with cogito-mem. Each is a `## ` section; each system is a `### ` entry with
the same fields: **TL;DR**, **Built** (write → store → find → read → maintain), **Trained?**,
**Numbers**, **Time / deletion**, **Limits**, **For us**.

- **A. Prompted agent memory systems** — an LLM extracts text facts on every write; off-the-shelf
  embeddings + BM25 (+ graph) on every read. Nothing learned end to end.
- **B. Trained memory managers** — RL or SFT trains an LLM to choose ADD/UPDATE/DELETE or to keep a
  compact state; retrieval and the answering model stay fixed.
- **C. Memory inside one model** — test-time-trained memories, recurrent slot memories, gated
  memory banks. Overwrite or decay by design; serve only their own decoder.
- **D. Large sparse memory layers** — product-key lookups over millions of slots, trained in
  pretraining; knowledge stored in weights.
- **E. Plug-in memories for a frozen LLM** — datastores, KV stores, trained adapters, per-corpus
  trained caches; tied to one reader (or one tokenizer).
- **F. Latent communication between agents** — hidden states or KV caches on the wire.
- **G. Text-side trimming between agents** — Caveman, prompt compressors, communication pruning.
- **H. Retrieval infrastructure and how retrievers are trained** — ANN indexes with streaming
  inserts/deletes, multi-vector search, reader-likelihood training.
- **I. Time, consolidation, capacity, benchmarks and protocols.**
- **J. Memory for your own chats:** what Claude and ChatGPT build in, plus claude-mem, OpenMemory and Basic
  Memory. This is the direct competition for cogito-mem, with our positioning against it.

Related reviews in the MrCogito repository's `docs/literature_review/` (not repeated here): ICAE, Gist, 500xCompressor, Activation
Beacon, CEPE, KVzip, Compressive Transformer and Infini-attention in
`learned_kv_context_compression.md`; RMT, Memorizing
Transformers, Block-Recurrent, AutoCompressor, Landmark attention in
`recurrent_memory_transformers.md`; capacity / information
bottleneck theory in `information_bottleneck_latent_capacity.md`.

### At a glance

| family | what is stored | how it is written | how it is found | trained end to end? | any LLM can use it? | time / deletion |
|---|---|---|---|---|---|---|
| A prompted systems | text facts, triples, summaries | LLM call per message (seconds, $) | embeddings + BM25 + graph, RRF/rerank, 0.15–1 s | no | yes (text) | timestamps; Zep bi-temporal; invalidate, not delete |
| B trained managers | text memory (or one compact state) | RL-trained LLM policy | fixed BM25 / embeddings | write policy only | yes (text) | ADD/UPDATE/DELETE ops |
| C memory in one model | weights or slots | gradient step / gated overwrite | forward pass | yes | no | decay / overwrite (forgets by design) |
| D sparse memory layers | weights (values) | pretraining | product keys, exact top-k | yes | no | none |
| E plug-in memories | raw chunks, KV, adapters, trained caches | encoder pass or per-corpus training | kNN / ANN | partly (adapter, cache) | one reader / one tokenizer | datastore swap, age tags |
| F latent channels | hidden states, KV | sender forward pass | n/a (pushed) | fuser/adapter only | same architecture or per-pair fuser | none |
| G text trimming | trimmed text | rules or a small classifier | n/a | classifier only | yes | none |
| J chat memory products | LLM summaries, Markdown notes, or the chat history | LLM summary on each save, or the assistant writes notes | vectors, RAG tool calls | no | the vendor's own, or any MCP client | mostly undocumented |
| cogito-mem v0 | the messages, word for word | append (milliseconds); embedding in the background | exact vector search + BM25, with time filters | no | any MCP client | two clocks, `as_of`, `retracts` |
| our E33/E33f | latent notes (64+64 numbers, 1 per 6 tokens) | feed-forward writer, 1M tokens in 0.45 s | reader's attention; E33f top-4 per round per token | yes | no (our decoders) | order / rank term (E33e); no delete |

**Are they trained?** In deployed agent memory (A) nothing is learned: writes are prompted LLM
calls and reads use off-the-shelf embedders. Learned pieces exist only as (B) RL-trained write
policies over text with fixed retrieval, (C/D) memories trained inside one model that cannot
serve another, and (E) adapters or caches trained per reader or per corpus. We found **no system
that trains the writer, the store's keys, the retriever and the consolidation pass together and
serves arbitrary LLMs through text** — the gap the proposal targets.

---

## A. Prompted agent memory systems

### MemGPT / Letta (2023→2026)
- Links: [2310.08560](https://arxiv.org/html/2310.08560), sleep-time compute [2504.13171](https://arxiv.org/abs/2504.13171), [repo](https://github.com/letta-ai/letta) (Apache-2.0, 25.2k★), [memory docs](https://docs.letta.com/configuration/memory).
- **TL;DR:** the LLM is an operating system that pages its own context: an in-prompt working block + FIFO queue, with recall and archival stores outside, edited by function calls.
- **Built:** write = agent tool calls; on 70 % context a warning, at 100 % half the queue is evicted into a recursive summary → store = text DB + archival text → find = tool-called search → read = text in prompt → maintain = "sleep-time" agent (now "Dreaming") rewrites in-context memory in the background over MemFS, a git-backed Markdown store where every edit is a commit.
- **Trained?** No.
- **Numbers:** DMR (deep memory retrieval) 35.3 → 93.4 % with GPT-4 Turbo. Sleep-time compute: same accuracy with ~5× less test-time compute; +13 / +18 % on Stateful GSM-Symbolic / AIME; 2.5× cheaper per query when amortised; gain tracks how predictable queries are. Letta reports a plain filesystem agent (grep over files) at 74.0 % on LoCoMo ([blog](https://www.letta.com/blog/benchmarking-ai-agent-memory)).
- **Time / deletion:** git history of memory edits — the only system with a full version chain.
- **For us:** the "sleep-time" pass is the prompted ancestor of our relink pass; git-as-memory is the append-only tape idea in engineering form.

### Mem0 / Mem0g (2025, 2026 algorithm)
- Links: [2504.19413](https://arxiv.org/html/2504.19413), [repo](https://github.com/mem0ai/mem0) (Apache-2.0, 67.3k★), [2026 algorithm blog](https://mem0.ai/blog/mem0-the-token-efficient-memory-algorithm) [V], OpenMemory MCP [docs](https://docs.mem0.ai/openmemory).
- **TL;DR:** extract facts with an LLM, then let a tool call decide ADD / UPDATE / DELETE / NOOP against the 10 most similar memories; Mem0g adds a Neo4j entity graph.
- **Built:** write = GPT-4o-mini over (summary, last 10 messages, new pair) → store = text facts in a vector DB (+ triples) → find = vector (+ graph) → read = text → maintain = none offline (2026: ADD-only, keep old facts, entity linking, rank-fused semantic + keyword + entity scores).
- **Trained?** No.
- **Numbers:** LoCoMo LLM-judge 66.88 (Mem0), 68.44 (Mem0g), full context 72.90; search p50/p95 0.148/0.200 s (Mem0), 0.476/0.657 s (Mem0g); ~7k tokens per conversation vs 26k raw. 2026 [V]: LoCoMo 92.5, LongMemEval 94.4, BEAM-1M 64.1, BEAM-10M 48.6, p50 0.88–1.09 s — managed platform with "proprietary optimizations". An independent run of a Mem0-based system scored LongMemEval 49.0 vs 82.4 for long-context GPT-5-mini ([2603.04814](https://arxiv.org/html/2603.04814)).
- **Time / deletion:** Mem0g marks conflicting edges invalid; 2026 version is ADD-only.
- **Limits:** every write is an LLM call; MemoryAgentBench measured Mem0 memory construction at 10,804 s vs 0.12 s for BM25 ([2507.05257](https://arxiv.org/html/2507.05257)).

### Zep / Graphiti (2025)
- Links: [2501.13956](https://arxiv.org/html/2501.13956v1), [repo](https://github.com/getzep/graphiti) (Apache-2.0, 31.8k★, MCP server).
- **TL;DR:** a temporal knowledge graph with three subgraphs (raw episodes, entity/fact edges, communities) and **two clocks**.
- **Built:** write = LLM extraction over current + last 4 messages, reflection, LLM entity dedup over 1024-d embeddings + full text → store = episodes (lossless) + edges + communities → find = cosine + BM25 + n-hop BFS, fused by RRF/MMR/mention count/node distance/cross-encoder → read = text → maintain = community refresh (incremental assignment "gradually diverges", needs periodic rebuild).
- **Trained?** No.
- **Numbers:** DMR 94.8 vs MemGPT 93.4; LongMemEval-S with gpt-4o 60.2 → 71.2, latency 28.9 → 2.58 s, context 115k → 1.6k tokens; temporal 45.1 → 62.4, knowledge-update 78.2 → 83.3; single-session-assistant fell 94.6 → 80.4. Graphiti "typically sub-second"; managed Zep "sub-200 ms" [V]. Zep's LoCoMo score is disputed: 65.99 (Mem0 paper), 75.14 (Zep), 59.22 (MemOS), 49.09 (MIRIX).
- **Time / deletion:** event time (`t_valid`, `t_invalid`) and ingestion time (`t'_created`, `t'_expired`); a contradicted edge is invalidated, never deleted. **The template for our bitemporal notes.**

### A-MEM (NeurIPS 2025)
- Links: [2502.12110](https://arxiv.org/html/2502.12110).
- **TL;DR:** Zettelkasten notes: each note has content, timestamp, LLM keywords/tags/context, a MiniLM embedding and links; a new note triggers link generation and "memory evolution" (rewriting neighbours).
- **Trained?** No. **Numbers:** ~1.2–2.5k tokens, < $0.0003 and 5.4 s per operation (GPT-4o-mini); text and tables of the paper disagree in places.
- **For us:** the closest prompted analogue of a relink pass, but it rewrites old notes — we only add edges.

### HippoRAG / HippoRAG 2 (2024, 2025)
- Links: [2405.14831](https://arxiv.org/abs/2405.14831), [2502.14802](https://arxiv.org/html/2502.14802) (MIT).
- **TL;DR:** hippocampal indexing theory: an OpenIE knowledge graph of phrase and passage nodes + synonym edges; Personalized PageRank from the query's matched triples ranks passages.
- **Trained?** No weights (DSPy-tuned filter prompt).
- **Numbers:** average F1 59.8 vs NV-Embed-v2 57.0, GraphRAG 49.6, RAPTOR 48.8; one-step retrieval matches IRCoT at 10–30× lower cost; indexing ~790 in / 257 out LLM tokens per passage (99.5 min vs 12.1 min dense); query 1.2 s vs 0.3 s dense.
- **For us:** link-following beats single-vector search on multi-hop — supports keeping edges next to vectors.

### RAPTOR, GraphRAG, MemTree (2024)
- Links: RAPTOR [2401.18059](https://arxiv.org/abs/2401.18059), GraphRAG [2404.16130](https://arxiv.org/abs/2404.16130), MemTree [2410.14052](https://arxiv.org/html/2410.14052).
- **TL;DR:** offline hierarchies. RAPTOR clusters and summarises recursively (+20 points on QuALITY with GPT-4); GraphRAG builds an entity graph + community summaries over ~1M tokens; MemTree inserts online by descending a similarity tree and rewriting ancestor summaries (3.27 LLM calls, ~10 s per insert; MSC-E 82.5 vs 80.7).
- **Limits:** RAPTOR/GraphRAG are batch-built — one new observation means ~3.7–3.9k LLM calls to rebuild (MemTree paper).
- **For us:** level-2 summary notes over clusters (our E32 two-level notebook) are the latent version.

### Generative Agents (2023)
- Links: [2304.03442](https://arxiv.org/html/2304.03442).
- **TL;DR:** a timestamped memory stream; retrieval score = recency (0.995 decay per game-hour) + LLM-rated importance (1–10) + cosine relevance, each min-max scaled; **reflection** fires when summed importance passes 150 (2–3 times a day) and stores reflections with pointers to cited memories.
- **For us:** the canonical "recency + relevance + importance" score; reflections with pointers = summary notes with edges.

### MemoryOS, MemOS, MIRIX, LightMem, Hindsight, Mastra OM, EverMemOS (2025–2026)
- MemoryOS [2506.06326](https://arxiv.org/html/2506.06326): short-term FIFO → mid-term "heat"-ranked segments → long-term persona (90 traits); LoCoMo F1 +49 % average over baselines; 4.9 LLM calls, 3.9k tokens per response.
- MemOS [2507.03724](https://arxiv.org/html/2507.03724v4), [repo](https://github.com/MemTensor/MemOS): the MemCube unit (content + origin, TTL, access control, version chain) moving between plaintext, KV-cache and parameter memory; self-reported LoCoMo 75.80 vs Mem0 64.57 / Zep 59.22; search mean/P99 440/777 ms at 10 QPS; KV injection cuts time-to-first-token up to 91.4 %.
- MIRIX [2507.07957](https://arxiv.org/html/2507.07957): six typed stores, each with its own agent; "active retrieval" generates a topic first; LoCoMo 85.38 vs full context 87.52.
- LightMem [2510.18866](https://arxiv.org/html/2510.18866): LLMLingua-2 pruning → topic segmentation → summaries → long-term store, updates deferred to an offline sleep pass; LongMemEval-S 68.64 % using 28k tokens and 18 calls vs A-MEM 62.60 % at 1.6M tokens and 987 calls.
- Hindsight [2512.12818](https://arxiv.org/html/2512.12818), [repo](https://github.com/vectorize-io/hindsight) (MIT, MCP endpoint): world facts / experiences / opinions / observations networks with entity, temporal and causal links; pgvector + BM25 + spreading activation + temporal search, RRF + cross-encoder; LongMemEval-S 83.6–91.4.
- Mastra Observational Memory [V] ([page](https://mastra.ai/research/observational-memory)): **no retrieval** — background agents keep a dated, priority-tagged append-only text log stable enough to be prompt-cached; ~6× text compression; LongMemEval-S 94.87 (gpt-5-mini).
- EverMemOS [2601.02163](https://arxiv.org/abs/2601.02163): "MemCells" (episode, facts, time-bounded foresight) grouped into "MemScenes"; Markdown as source of truth.
- Others: LangMem ([repo](https://github.com/langchain-ai/langmem)), Cognee ([repo](https://github.com/topoteretes/cognee), BEAM 0.67 at 10M, self-declared non-comparable), Memobase ([repo](https://github.com/memodb-io/memobase), "<100 ms" SQL profile reads [V]), Supermemory ([repo](https://github.com/supermemoryai/supermemory), "~50 ms" profile reads [V]), Second-Me ([2503.08102](https://arxiv.org/html/2503.08102), top layer a Qwen2.5-7B trained with SFT + DPO — memory in weights), ReadAgent ([2402.09727](https://arxiv.org/abs/2402.09727), page gists + on-demand page lookup, 3.5–20× effective context), MemoryBank ([2305.10250](https://arxiv.org/abs/2305.10250), Ebbinghaus forgetting curve).

**Family verdict for us:** the engineering is mature on *time* (bi-temporal edges, version chains,
append-only logs) and on *protocols* (MCP servers). What none has: a learned writer (writes cost an
LLM call each — hours to build at scale), a learned retriever, or a learned consolidation pass;
search is 0.15–1 s, and "< 100 ms" exists only for SQL profile lookups [V].

---

## B. Trained memory managers

### Memory-R1 (2025, ACL 2026)
- Links: [2508.19828](https://arxiv.org/html/2508.19828), [ACL](https://aclanthology.org/2026.acl-long.583/).
- **TL;DR:** PPO/GRPO trains (1) a manager that picks ADD/UPDATE/DELETE/NOOP and (2) an answer agent that filters ~60 retrieved memories; reward = exact match of a frozen answerer after the edit; only 152 LoCoMo QA pairs.
- **Numbers:** LoCoMo judge 62.74 vs Mem0 45.68 (LLaMA-3.1-8B). **Retrieval stays plain similarity RAG.**

### MEM1, MemAgent, Mem-α, AgeMem, ReSum, Fine-Mem, MemGen (2025–2026)
- MEM1 [2506.15841](https://arxiv.org/abs/2506.15841), [repo](https://github.com/MIT-MI/MEM1): RL keeps one constant-size internal state per turn; 3.5× better and 3.7× less memory than Qwen2.5-14B on 16-objective multi-hop QA.
- MemAgent [2507.02259](https://arxiv.org/abs/2507.02259), [repo](https://github.com/BytedTsinghua-SIA/MemAgent): reads 5K chunks into a 1K overwritten memory; DAPO RL with a binary answer reward on 32,768 synthetic RULER-HotpotQA samples (~32K tokens); 81 % at 7K, 71–72 % at 3.5M tokens.
- Mem-α [2509.25911](https://arxiv.org/html/2509.25911v1): Qwen3-4B learns insert/update/delete over core/episodic/semantic memory via GRPO; reward = QA accuracy + format + compression + validity; BM25 retrieval and a frozen 32B answerer; MemoryAgentBench 0.592 vs long-context 0.461; trained ≤30k tokens, works past 400k.
- AgeMem [2601.01885](https://arxiv.org/abs/2601.01885) [abs]: one policy for long- and short-term memory, step-wise GRPO.
- ReSum [2509.13313](https://arxiv.org/abs/2509.13313): periodic summaries + GRPO; +4.5 % untrained, +8.2 % more after RL.
- Fine-Mem [2601.08435](https://arxiv.org/abs/2601.08435) (preprint): step rewards from auxiliary QA per chunk + credit to memory ops by which items were used as evidence — a denser reward.
- MemGen [2509.24704](https://arxiv.org/abs/2509.24704) (ICLR 2026) [abs]: RL-trained trigger + "weaver" that writes latent memory tokens; ElasticMem [2605.30690](https://arxiv.org/abs/2605.30690) [abs]: variable latent budget per memory, GRPO.

**Family verdict for us:** reward = "did the downstream answer get it right" is the right signal,
and it works from tiny data (152 pairs). But the learned part is only a text-editing policy at
3–14B parameters, with fixed retrieval, tested ≤3.5M tokens. Our latent memory would train the
store and retriever themselves, with the same outcome reward as a late fine-tune.

---

## C. Memory inside one model

### Titans, MIRAS, ATLAS, Nested Learning / HOPE (2024–2025)
- Links: Titans [2501.00663](https://arxiv.org/abs/2501.00663) (NeurIPS 2025), unofficial [titans-pytorch](https://github.com/lucidrains/titans-pytorch), Titans Revisited [2510.09551](https://arxiv.org/abs/2510.09551); MIRAS [2504.13173](https://arxiv.org/abs/2504.13173) [abs]; ATLAS [2505.23735](https://arxiv.org/abs/2505.23735); Nested Learning [2512.24695](https://arxiv.org/abs/2512.24695) [abs].
- **TL;DR:** an MLP long-term memory learns key→value pairs **at test time** by gradient steps on ‖M(k)−v‖² with momentum ("surprise") and a forget gate; read = M(q). ATLAS fits the memory to a sliding window ("Omega rule") with polynomial feature maps (matrix capacity ~O(d_k^p)) and Muon.
- **Trained?** Yes, end to end from scratch (Titans 170–760M params, 15–30B tokens, 4K training length; ATLAS up to 1.3B / 100B tokens).
- **Numbers:** Titans claims > 2M context; ATLAS claims > 80 % on BABILong at 10M tokens. Titans Revisited: the memory beats attention-only models, but Titans does not consistently beat baselines.
- **Time / deletion:** recency only through the forget gate (weight decay) — **forgets by design**, the opposite of our "never forget".

### TTT layers and TTT-E2E (2024–2025)
- Links: [2407.04620](https://arxiv.org/abs/2407.04620) ([jax](https://github.com/test-time-training/ttt-lm-jax), [pytorch](https://github.com/test-time-training/ttt-lm-pytorch)); TTT-E2E [2512.23675](https://arxiv.org/abs/2512.23675), [code](https://github.com/test-time-training/e2e).
- **TL;DR:** the hidden state is a model updated by a self-supervised step; TTT-E2E updates the last-quarter MLPs of an 8K sliding-window transformer by next-token loss on the context with meta-learned initial weights.
- **Numbers:** TTT-E2E at 3B / 164B tokens scales with context like full attention and is 2.7× faster at 128K, **but needle-in-a-haystack at 128K is 0.06 vs 0.99 for full attention**.
- **For us:** gradient-written memories compress gist, not exact facts — they fail the lookup tasks our text checks test.

### ARMT, LM2, MemoryLLM, M+, Larimar, Memory Mosaics (2024–2025)
- ARMT [2407.04841](https://arxiv.org/abs/2407.04841), [repo](https://github.com/RodkinIvan/associative-recurrent-memory-transformer): RMT memory tokens + a delta-rule associative matrix per layer (GPT-2 137M); BABILong QA1 at 50M tokens best 79.9 %, mean 49.6 ± 40.4; strictly sequential.
- LM2 [2502.06049](https://arxiv.org/abs/2502.06049), [repo](https://github.com/convergence-ai/lm2): 2,048 × 2,048 memory slots read by cross-attention with input/forget/output gates; 1.2B + 0.5B memory; BABILong +37.1 % over RMT; MMLU 28.0 → 29.4.
- MemoryLLM [2402.04624](https://arxiv.org/abs/2402.04624): Llama2-7B + 1.07B-param latent pool; each write replaces 256 random slots per layer (~3.3 %); retention decays roughly exponentially.
- **M+** [2502.00592](https://arxiv.org/abs/2502.00592), [repo](https://github.com/wangyu-ustc/MemoryLLM): dropped slots move to a long-term store (≤150K per layer, CPU-offloadable) **with age tags**; a co-trained retriever (d/20 query/key projectors) fetches 2,560 tokens per step sorted by age. Retention 20K → 160K tokens, **but the retriever finds only ~30 % of the needed tokens**, and it trails the base model on HotpotQA / MuSiQue. **The closest prior art to a trained latent store with a trained retriever** — inside one LLM.
- Larimar [2403.11901](https://arxiv.org/abs/2403.11901) (ICML 2024), [repo](https://github.com/IBM/larimar): BERT-large encoder writes into a 512 × 768 Kanerva-style memory by least squares; decoder (GPT2-large / GPT-J) reads it as KV; one-shot edits in 1.1–1.7 s; a fact is forgotten by writing it with α = −1.
- Memory Mosaics v2 [2507.03285](https://arxiv.org/abs/2507.03285) (NeurIPS 2025 oral), [repo](https://github.com/facebookresearch/MemoryMosaics): kernel-regression associative memories at three time scales replace attention; 9.9B / 1T tokens; RULER multi-doc QA at 32K 53.4 vs 41.1 for a same-data transformer.

**Family verdict for us:** all fixed-size or overwriting; time = decay or random drop; serve one
decoder. Useful as theory (associative-memory capacity, gated writes) — not as the service design.

---

## D. Large sparse memory layers

- **Product-Key Memory** [1907.05242](https://arxiv.org/abs/1907.05242): exact top-k over 512² = 262k slots via two half-key searches, cost O((√|K| + k²)·d_q); a 12-layer model with memory beats a 24-layer one (perplexity 15.62 vs 16.02) at 2× speed; query BatchNorm raises key usage 64 → 98 %.
- **PEER** [2407.04153](https://arxiv.org/abs/2407.04153): product-key retrieval over > 1M tiny experts.
- **Memory Layers at Scale** [2412.09764](https://arxiv.org/abs/2412.09764), [repo](https://github.com/facebookresearch/memory) (CC-BY-NC): one shared product-key pool replaces 1–3 FFNs, up to 64M keys / 128B params; NaturalQuestions 13.7 vs 7.8 dense at 1.3B, 27.1 vs 25.2 at 8B; custom CUDA kernels.
- **UltraMem / UltraMemV2** [2411.12364](https://arxiv.org/abs/2411.12364), [2508.18756](https://arxiv.org/abs/2508.18756): 20M slots, lower latency than MoE; 120B total / 2.5B active.
- **Hierarchical memories (Apple)** [2510.02375](https://arxiv.org/abs/2510.02375) (ICLR 2026): DCLM clustered into a 4-level tree (65,536 leaves), one FFN block per cluster fetched by sentence embedding; a 160M model + 18M fetched params (from a 4.6B bank) matches a model > 2× larger; **attachable to frozen Gemma-3-270M / Qwen2.5-0.5B / Llama-3.2-1B**; masking 1/16 of the bank removes that knowledge (70 → 20 %).
- **Sparse memory finetuning** [2510.15103](https://arxiv.org/abs/2510.15103): update only TF-IDF-ranked slots; forgetting on NaturalQuestions −11 % vs −89 % full finetune.
- **For us:** product keys give exact, sub-linear top-k inside a network — a candidate for the
  librarian's first-stage search if we keep it inside the model; "mask a block to delete
  knowledge" is the only clean deletion story in parametric memory.

---

## E. Plug-in memories for a frozen LLM

- **kNN-LM** [1911.00172](https://arxiv.org/abs/1911.00172): interpolate next-token distribution with a kNN lookup; WikiText-103 perplexity 15.79 without training; swap the datastore to change domain.
- **RETRO** [2112.04426](https://arxiv.org/abs/2112.04426): frozen BERT retriever over 64-token chunks, 2T-token database queried with ScaNN in ~10 ms; matches GPT-3 on the Pile with 25× fewer parameters.
- **Atlas** [2208.03299](https://arxiv.org/abs/2208.03299), [repo](https://github.com/facebookresearch/atlas): 42 % on NaturalQuestions from 64 examples; updatable index (fp16 Wikipedia index 49 GB, ~4 GB with PQ).
- **Memory Decoder** [2508.09874](https://arxiv.org/abs/2508.09874) (NeurIPS 2025), [repo](https://github.com/LUMIA-Group/MemoryDecoder): a 124M–0.5B decoder trained to imitate kNN-LM output (0.5·KL + 0.5·LM loss), mixed into **any LLM sharing the tokenizer**; perplexity −6.17 average; 1.28× latency vs 1.51× in-context RAG; another tokenizer needs new embeddings + ~10 % of the training budget. **The best published "plug-and-play" result — but it stores knowledge in weights, not an addressable, appendable store.**
- **MLP Memory** [2508.01832](https://arxiv.org/abs/2508.01832) (ICLR 2026): an MLP imitating a kNN retriever over all pretraining data; +12.3 % QA, 2.5× faster than RAG.
- **KBLaM** [2410.10450](https://arxiv.org/abs/2410.10450) (ICLR 2025), [repo](https://github.com/microsoft/KBLaM): each triple → key/value token via a sentence encoder + trained linear adapters; "rectangular" attention keeps cost linear; > 10K triples on an 8B model; degrades on KBs unlike its synthetic training KB; one adapter per model.
- **xRAG** [2405.13792](https://arxiv.org/abs/2405.13792), [repo](https://github.com/Hannibal046/xRAG): a 2-layer MLP projector (0.46 % of Mistral-7B) turns a frozen retriever's 4096-d embedding into **one token** for a frozen LLM; stage 1 rebuild the document, stage 2 answer loss + KL to full-text RAG; Mistral 36.5 (no retrieval) → 42.5 vs 43.6 full RAG; 3.53× fewer FLOPs; weaker on multi-hop.
- **Memory³** [2407.01178](https://arxiv.org/abs/2407.01178): a 2.4B model whose memory is sparse KV (8 of 128 tokens per head, 22 layers, per 128-token chunk) + residual VQ (11.4×); 1.1e8 chunks ≈ 4 TB; BGE-M3 + FAISS retrieval every 64 generated tokens; 733 vs 1,131 tok/s; memory training diverged at 120B tokens.
- **MemLong** [2408.16967](https://arxiv.org/abs/2408.16967), [repo](https://github.com/Bui1dMySea/MemLong): frozen layer-13 KV stored per chunk in FAISS, read by LoRA-trained upper layers; 4K → 80K context on one 3090; prunes old, rarely used entries.
- **CAMELoT** [2402.13449](https://arxiv.org/abs/2402.13449): training-free 10K slots per layer, merge if cosine > 0.93 else replace oldest; −29.7 % perplexity on arXiv.
- **MemoRAG** [2409.05591](https://arxiv.org/abs/2409.05591), [repo](https://github.com/qhjqhj00/MemoRAG): a light long-context "memory model" (~400K–1M tokens via KV compression) writes **clues** that steer a retriever and a separate generator — a two-model split like ours (memory side / answer side).
- **Cartridges** [2506.06266](https://arxiv.org/abs/2506.06266), [repo](https://github.com/HazyResearch/cartridges): a trainable KV prefix per corpus, trained by **context distillation on synthetic self-study conversations** (KL to the same frozen model with the chunk in context); 38.6× less memory and 26.4× more throughput than in-context learning; MTOB effective context 128K → 484K; cartridges concatenate without joint training; ~30 min on 8×H100 per corpus; one model only. Plain next-token training on the corpus was not competitive.
- **Generative Adapter** [2411.05877](https://arxiv.org/abs/2411.05877) [abs], **Doc-to-LoRA** ([ICML 2026](https://proceedings.mlr.press/v306/charakorn26a.html), [repo](https://github.com/SakanaAI/doc-to-lora)), DyPRAG [2503.23895](https://arxiv.org/abs/2503.23895): a hypernetwork maps a document to a LoRA in one pass (Generative Adapter: StreamingQA F1 19.5 → 31.5; Doc-to-LoRA: near-perfect needle at > 4× native context).

**Family verdict for us:** "plug-in" always means one reader, one tokenizer or one adapter per
reader. The training recipes transfer directly: context distillation (Cartridges), reconstruction
then answer-with-KL (xRAG), imitate-a-retriever (Memory Decoder).

---

## F. Latent communication between agents

| work | what crosses the wire | requirement on the two models | result vs text | code |
|---|---|---|---|---|
| CIPHER [2310.06272](https://arxiv.org/abs/2310.06272) (ICLR 2024) | softmax-weighted vocabulary embeddings | shared tokenizer; training-free | +0.5–5.0 % over language debate | — |
| Activation communication [2501.14082](https://arxiv.org/html/2501.14082) (ICML 2025) | A's layer-26 activation replaces B's last-token activation | truncation across families; optional linear map | up to +27 % at < ¼ compute, but GSM8k 64.0 vs 75.0 for text (100-sample subsets) | — |
| DroidSpeak [2411.02820](https://arxiv.org/abs/2411.02820) | prefix KV cache, a few layers recomputed | fine-tunes of one base | 4× throughput, 3.1× faster first token | — |
| KVComm [2510.03346](https://arxiv.org/html/2510.03346v3) (ICLR 2026) | KV of 30–70 % of layers | same base model | HotpotQA (Llama-3.2-3B): text 0.43, KVComm 0.57–0.65, single-model bound 0.73 | [repo](https://github.com/Zephyroam/KVComm) |
| C2C [2510.03215](https://arxiv.org/abs/2510.03215) (ICLR 2026) | sender KV projected, gated, fused into receiver KV | both frozen, per-pair trained fuser (500k OpenHermes), works across Qwen/Llama/Gemma 0.6–14B | +3.1–5.4 % vs text (text baseline = one-sentence hint ≤ 256 tokens), 2.5× faster | [repo](https://github.com/thu-nics/C2C) |
| LatentMAS [2511.20639](https://arxiv.org/html/2511.20639) | last-layer hidden states via closed-form map; shared KV working memory | same layer shapes; training-free | up to +14.6 %, 70.8–83.7 % fewer output tokens, 4–4.3× faster | [repo](https://github.com/Gen-Verse/LatentMAS) |
| Interlat [2511.09149](https://arxiv.org/html/2511.09149) (ACL 2026) | last hidden states → trained adapter; compressed to 8 latent steps | receiver trained; Qwen latents → Llama actor works | ALFWorld 70.48/65.42 vs text 64.29/62.44; MATH 36.88 vs CoT 38.35; 24× faster | [repo](https://github.com/XiaoDu-flying/Interlat) |
| ThoughtComm [2510.20733](https://arxiv.org/html/2510.20733) (NeurIPS 2025) | sparse-autoencoder "thoughts" as prefix (text still broadcast) | autoencoder + adapter trained on 500 examples | MATH 93.0 vs 75.8 for multi-agent fine-tuning; no pure-text baseline | — |
| KV mappers [2608.03893](https://arxiv.org/abs/2608.03893), [2608.30963](https://arxiv.org/abs/2608.30963) [abs] | KV mapped across models | ridge: same family and head shapes; "universal layer" cross-family | 73–98 % of native on 4/6 pairs; Llama-70B → Qwen-7B 44.0 vs 45.7 native, 899 → 138 ms | — |

**Family verdict for us:** latent channels save time and tokens (2.5–24× faster, 70–84 % fewer
tokens) but beat a *fair* text baseline by only a few points; no latent format is read untrained
across unrelated families. Same conclusion as our E35 (vector messages, 0 % facts): a latent wire
to a foreign LLM needs a per-reader adapter; to arbitrary LLMs, the wire should be text.

---

## G. Text-side trimming between agents

### Caveman (2026)
- Links: [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) (~113k★; licence shown as Apache-2.0 on the repo page, MIT in third-party listings — unverified), [HONEST-NUMBERS](https://github.com/JuliusBrussee/caveman/blob/main/docs/HONEST-NUMBERS.md), [cavecrew](https://github.com/JuliusBrussee/caveman/tree/main/skills/cavecrew).
- **TL;DR:** a Claude Code skill that makes the agent answer in terse "caveman" language. Keeps code, paths, errors, numbers and negations verbatim; full sentences for security and irreversible actions; drops articles, greetings, recaps. `caveman-compress` rewrites memory files (−33.2 % input). For agent-to-agent use, `cavecrew` subagents report in fixed compact formats (`path:line`, one-line findings).
- **Numbers (its own):** tagline "cuts 65 % of tokens"; README 10-question test: 6,983 output tokens plain, 4,334 with "answer concisely", 4,119 with /caveman — **~3 % over a plain "be concise" instruction**, while the rules add ~1,160 input tokens. One user: −44.1 % output tokens, +0.06 % total cost. Token counts "do not prove semantic or technical equivalence".
- **Choosing what is important:** fixed rules (keep exact identifiers and numbers, drop filler); no learned importance and no published general reduction rate for agent-to-agent traffic.
- **For us:** its keep-list (names, numbers, paths verbatim) is exactly what latent compression drops first (Cramming: capacity set by cross-entropy; vec2text/ICAE fail on random strings) → return exact spans for rare tokens.

### CAVEWOMAN, LLMLingua-2, Selective Context, AgentPrune, AgentDropout, Optima
- CAVEWOMAN (Adobe) [2606.24083](https://arxiv.org/abs/2606.24083) [abs]: compressing outputs cuts cost 1.4–2.4×; compressing **inputs** raises net cost (~1.15×, up to 2.7×) and "accuracy collapses"; on non-reasoning models ~half of correct answers no longer entail the reference.
- LLMLingua-2 [2403.12968](https://arxiv.org/abs/2403.12968), [repo](https://github.com/microsoft/LLMLingua): token classification (XLM-R/mBERT) trained on LLM-distilled labels; 2–5× compression, 1.6–2.9× latency gain, works across target LLMs.
- Selective Context [2310.06201](https://arxiv.org/abs/2310.06201): −50 % context, −32 % time, −0.023 BERTScore, −0.038 faithfulness.
- AgentPrune [ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/bbc461518c59a2a8d64e70e2c38c4a0e-Abstract-Conference.html), [repo](https://github.com/yanweiyue/AgentPrune): prune the communication graph once; 28.1–72.8 % fewer tokens, $5.6 vs $43.7.
- AgentDropout [2503.18891](https://arxiv.org/pdf/2503.18891): drops agents and links per round; −21.6 % prompt, −18.4 % completion tokens, +1.14 performance.
- Optima [2410.08115](https://arxiv.org/abs/2410.08115): trains agents on task score + token use + readability; up to 2.8× better with < 10 % of the tokens on information-exchange tasks.
- **Family verdict for us:** the big wins come from **not sending** (pruning who talks, retrieving
  only what is needed), not from rewording what is sent. That is an argument for a pull memory
  (query → only relevant facts) over pushed summaries — the same lesson as E35 vs E33f.

---

## H. Retrieval infrastructure and how retrievers are trained

### ANN indexes at 10^6–10^8 vectors
- **HNSW** [1603.09320](https://arxiv.org/abs/1603.09320): logarithmic search, incremental inserts; **no real deletion** — FAISS HNSW "does not support removing vectors" ([wiki](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes)); hnswlib offers `mark_deleted` tombstones + `replace_deleted` ([repo](https://github.com/nmslib/hnswlib)); churn leaves unreachable points (MN-RU fix [2407.07871](https://arxiv.org/abs/2407.07871) [abs]).
- **FreshDiskANN** [2105.09613](https://arxiv.org/abs/2105.09613): lazy deletes (DeleteList, filtered at search) + batch neighbourhood rewiring after 1–10 % deletes; ~1,800 inserts + 1,800 deletes / s at 95 %+ 5-recall@5 in ~5 ms; merging 30M into 800M took ~8,400 s on 40 threads. Keeps PQ codes in RAM, full vectors on SSD.
- **DiskANN** ([NeurIPS'19](https://papers.nips.cc/paper/2019/hash/09853c7fb1d3f8ee67a61b6bf4a7f8e6-Abstract.html)): 1B points on 64 GB RAM + SSD at 95 %+ 1-recall@1 under 5 ms.
- **CPU vs GPU at 100M** (Meta/NVIDIA vendor test, H100 vs Xeon 8480CL, 100M × 96-d, 95 % recall@10, single query, [blog](https://engineering.fb.com/2025/05/08/data-infrastructure/accelerating-gpu-indexes-in-faiss-with-nvidia-cuvs/)): HNSW CPU 0.56 ms / CAGRA GPU 0.23 ms; IVF-Flat 0.75 / 0.39 ms; IVF-PQ 0.49 / 0.17 ms; build HNSW 3,322 s vs CAGRA 519 s. CAGRA paper [2308.15136](https://arxiv.org/abs/2308.15136).
- **Big-ANN NeurIPS'23 streaming track** ([site](https://big-ann-benchmarks.com/neurips23.html)): 30M × 100-d, insert:delete:search ≈ 4:4:1, 8 vCPU / 8 GB; FreshDiskANN baseline recall@10 0.883.
- **Full precision vs quantised:** Flat, IVF-Flat, HNSW-Flat and CAGRA work on full-precision vectors (pay in RAM: 10^8 × 1024-d fp16 = 205 GB; × 64-d bf16 = 12.8 GB). IVF-PQ, ScaNN [1908.10396](https://arxiv.org/abs/1908.10396), DiskANN's in-RAM codes and ColBERTv2/PLAID need PQ/VQ. A DiskANN-style split keeps stored vectors exact (codes only shortlist, full vectors re-rank).
- **Multi-vector:** ColBERTv2 [2112.01488](https://arxiv.org/abs/2112.01488), PLAID [2205.09707](https://arxiv.org/abs/2205.09707) (7× GPU / 45× CPU over ColBERTv2; tens of ms GPU at 140M passages), MUVERA [2405.19504](https://arxiv.org/abs/2405.19504) (multi-vector → single-vector search, ~10 % higher recall and 90 % lower latency than PLAID on BEIR). Learned sparse: SPLADE [2207.03834](https://arxiv.org/abs/2207.03834) within 4 ms of BM25.
- **Single-vector limit:** LIMIT [2508.21038](https://arxiv.org/html/2508.21038) — embedding dimension bounds which top-k subsets are reachable; on 50k docs best single-vector Recall@100 18.9, multi-vector 54.8, BM25 93.6 (extrapolated document limits for top-2 — 500k at d = 512, 4M at d = 1024 — use a fit on d ≤ 45; treat with care). **Our notes are many vectors per page — multi-vector by construction.**
- **Model-as-index:** DSI [2202.06991](https://arxiv.org/abs/2202.06991) fails to scale (8.8M passages "unsolved", [2305.11841](https://arxiv.org/abs/2305.11841)) and forgets as documents are added (DSI++ [2212.09744](https://arxiv.org/abs/2212.09744)) — avoid storing the index in weights for an append-only memory.

### Training the retriever from the reader's signal
- REALM [2002.08909](https://arxiv.org/abs/2002.08909): masked-LM loss marginalised over retrieved docs; async re-embedding every ~500 steps; a 30× staler index drops NQ EM 38.2 → 28.7.
- RAG [2005.11401](https://arxiv.org/abs/2005.11401): answer likelihood marginalised over top-k; doc index frozen.
- **Atlas** [2208.03299](https://ar5iv.labs.arxiv.org/html/2208.03299): retriever softmax matched (KL) to ADist / EMDR² / **PDist** (softmax of the reader's answer log-likelihood per doc) / LOOP; 64-shot: fixed 42.2, ADist 43.0, EMDR² 43.3, LOOP 43.7, PDist 45.7; query-side-only training (no index refresh) 45.7 vs 44.1, re-index every 1k steps ≈ +30 % compute.
- **REPLUG LSR** [2301.12652](https://arxiv.org/html/2301.12652): KL(retriever ‖ softmax(P_LM(y | d, x)/τ)) over top-20 with a **frozen black-box LM**; GPT-3 175B LM +6.3 %, Codex MMLU +5.1 %.
- In-Context RALM [2302.00083](https://arxiv.org/html/2302.00083v3), [repo](https://github.com/AI21Labs/in-context-ralm): retrieve every 4 tokens; a reranker trained on the frozen LM's likelihood ≈ 2× LM size.
- RA-DIT [2310.01352](https://arxiv.org/abs/2310.01352): alternate LM and retriever tuning; +8.9 % 0-shot at 65B.
- **AAR** [2305.17331](https://arxiv.org/abs/2305.17331), [repo](https://github.com/OpenMatch/Augmentation-Adapted-Retriever): a retriever trained on a **small** source LM's preferences transfers zero-shot to unseen targets from 250M Flan-T5 to 175B InstructGPT — evidence that a memory trained with our small decoder can serve big foreign LLMs (shown for text passages only).
- Reader cross-attention as labels: [2012.04584](https://arxiv.org/abs/2012.04584).
- Contrastive retrievers: DPR [2004.04906](https://arxiv.org/abs/2004.04906) (+9–19 top-20 over BM25), Contriever [2112.09118](https://arxiv.org/abs/2112.09118), E5 [2212.03533](https://arxiv.org/abs/2212.03533), E5-Mistral [2401.00368](https://arxiv.org/abs/2401.00368), GTE [2308.03281](https://arxiv.org/abs/2308.03281), BGE-M3 [2402.03216](https://arxiv.org/abs/2402.03216), NV-Retriever [2407.15831](https://arxiv.org/abs/2407.15831) (positive-aware hard-negative mining).
- Multi-hop retrieval: Baleen [2101.00436](https://arxiv.org/abs/2101.00436) (condensed per-hop context, learned hop order), IRCoT [2212.10509](https://arxiv.org/abs/2212.10509) (+21 retrieval, +15 QA), HippoRAG (above).

### Training the writer / what one unit should hold
- Proposition indexing — Dense X [2312.06648](https://arxiv.org/html/2312.06648v3), [repo](https://github.com/chentong0/factoid-wiki): Flan-T5-Large trained on 42,857 GPT-4 paragraph→proposition pairs; propositions as units raise Recall@5 by +12.0 (SimCSE), +9.3 (Contriever).
- EntiGraph / synthetic continued pretraining [2409.07431](https://arxiv.org/html/2409.07431), [repo](https://github.com/ZitongYang/Synthetic_Continued_Pretraining): 1.3M source tokens → 455M synthetic relation text; Llama-3-8B QuALITY closed-book 39.5 → 56.2; stacks with RAG (62.6).
- Context distillation for knowledge modules [2503.08727](https://arxiv.org/abs/2503.08727); PISCO [2501.16075](https://arxiv.org/abs/2501.16075) (16× compression, 0–3 % loss); PCC [ACL 2025](https://aclanthology.org/2025.acl-long.1394/) [abs] (reconstruction + completion pretraining; "adaptable to different downstream LLMs", mechanism unverified); LLoCO [2404.07979](https://arxiv.org/abs/2404.07979).
- Cramming 1568 tokens into one vector — [ACL 2025](https://aclanthology.org/2025.acl-long.948), [repo](https://github.com/yurakuratov/hidden_capacity): per-sample optimised input vectors for a frozen LM; at ≥ 0.99 token accuracy one vector holds Llama-3.1-8B 1568 tokens, Llama-3.2-1B 512, Pythia-160M 80; capacity ≈ linear in vector count, set by the text's cross-entropy; vectors don't generalise across initialisations. Follow-up [2505.21189](https://arxiv.org/abs/2505.21189) [abs]: the vectors form connected regions, so a trained encoder may be feasible. **An upper bound for any trained encoder, not an operating point.**
- Synthetic long-context tasks as **training** signal: Artificial Needles [2406.19292](https://arxiv.org/abs/2406.19292) (+10.5 % MDQA), IN2 / FILM-7B [2404.16811](https://arxiv.org/abs/2404.16811), BABILong [2406.10149](https://arxiv.org/abs/2406.10149) (RMT fine-tuned to 50M tokens). As **tests** with warnings: RULER [2404.06654](https://arxiv.org/abs/2404.06654); **NoLiMa** [2502.05167](https://arxiv.org/abs/2502.05167) (when question and needle share no words, 11 of 13 models fall below 50 % of short-context score at 32K; literal-match needles teach a shortcut); ProLong [2410.02660](https://arxiv.org/abs/2410.02660) rejects NIAH and perplexity as development signals.

---

## I. Time, consolidation, capacity, benchmarks and protocols

### Time
- Bi-temporal facts (Zep, above): event time + ingestion time; invalidate, never delete.
- Event sourcing ([Fowler](https://martinfowler.com/eaaDev/EventSourcing.html)): "capture all changes to an application state as a sequence of events"; state = replay, snapshots cut replay time. **The tape is an event log; notes, links and summaries are derived, rebuildable views.**
- TempRALM [2401.13222](https://arxiv.org/abs/2401.13222): time-aware retrieval up to +74 % over plain RALM, no retraining; timestamp-conditioned LMs [2106.15110](https://arxiv.org/abs/2106.15110).
- LongMemEval's time-aware query expansion: +6.8–11.3 % temporal recall with GPT-4o; adding extracted facts to keys +9.4 % recall.

### Consolidation
- Complementary learning systems: hippocampus stores specifics fast, neocortex learns structure slowly by interleaved replay ([McClelland, McNaughton, O'Reilly 1995](https://stanford.edu/%7Ejlmcc/papers/McCMcNaughtonOReilly95.pdf)); replay can be goal-weighted and schema-consistent information is learned fast ([Kumaran, Hassabis, McClelland 2016](https://web.stanford.edu/~jlmcc/papers/KumaranHassabisMcClelland16FinalMS.pdf)); cells that fired together in a task fire together in sleep ([Wilson & McNaughton 1994](https://pubmed.ncbi.nlm.nih.gov/8036517/)).
- ML offline passes: sleep-time compute (Letta), reflection (Generative Agents), RAPTOR / GraphRAG trees, A-MEM evolution, LightMem deferred updates; index-side: FreshDiskANN merges, REALM re-indexing. **None has a learned objective** — all prompted or heuristic.

### Capacity
- Modern Hopfield networks [2008.02217](https://arxiv.org/abs/2008.02217): attention = Hopfield update; capacity exponential in dimension for well-separated patterns; poorly separated patterns collapse to **metastable averages** — the mechanism behind our diffuse reads. Dense associative memory [1606.01164](https://arxiv.org/abs/1606.01164), [1702.01929](https://arxiv.org/abs/1702.01929).
- Attention approximates Kanerva's sparse distributed memory [2111.05498](https://arxiv.org/abs/2111.05498).
- Associative memories store ∝ parameter count [2412.06538](https://arxiv.org/abs/2412.06538); LMs store ~2 bits of knowledge per parameter [2404.05405](https://arxiv.org/abs/2404.05405).

### Benchmarks
- LoCoMo [2402.17753](https://arxiv.org/abs/2402.17753): ~9K tokens per conversation, 7,512 QA (20.6 % temporal; best temporal F1 42.1 vs humans 92.6).
- LongMemEval [2410.10813](https://arxiv.org/abs/2410.10813): 500 questions (extraction, multi-session, temporal, knowledge update, abstention); S ≈ 115k tokens, M ≈ 1.5M tokens.
- BEAM [2510.27246](https://arxiv.org/abs/2510.27246): conversations up to 10M tokens.
- MemoryAgentBench [2507.05257](https://arxiv.org/html/2507.05257): selective forgetting + multi-hop ≤ 28 % for every method (Mem0 2.0, Zep 3.0); construction time Mem0 10,804 s vs BM25 0.12 s.
- **No benchmark goes beyond 10M tokens**; scores across papers are not comparable (judge, backbone and top-k differ).

### Protocols
- MCP reference memory server ([repo](https://github.com/modelcontextprotocol/servers/tree/main/src/memory)): entity / relation / observation tools over a JSONL file — no timestamps, validity or provenance.
- OpenMemory MCP (Mem0): add / search / list / delete-all memories.
- Google A2A v1.0 ([spec](https://a2a-protocol.org/latest/specification/)): JSON-RPC / gRPC / REST, Agent Cards, task states — no memory operations (only `contextId` grouping and task history).
- W3C AI Agent Memory Interoperability CG ([charter](https://www.w3.org/community/ai-agent-memory-interop/2026/07/16/charter-ai-agent-memory-interoperability-community-group-v1-0/), June 2026), referencing IETF draft `draft-saihm-memory-protocol` (cell format, encryption, audit, erasure) — early, not a standard.
- **Jev** (TypeSafe "System One" decision model; [OpenRouter guide](https://openrouter.ai/docs/guides/community/jev.md), [docs](https://docs.typesafe.ai)): a request is `state` (text/images) + named typed `questions`; four primitives — **Choice** (option + per-option probabilities + confidence), **Noul** (probability a condition holds), **Score** (probability-weighted position on an ordered scale), **Box** (image region); answers keyed by question name, **no generated text**, every response carries `usage.cost`. REFLEX [2609.26532](https://arxiv.org/abs/2609.26532) [abs]: routing through Jev gave 95 % success with 72.7 % fewer strong-LLM calls. Not a memory framework — but the right shape for a memory's query interface (typed questions in, calibrated typed answers + evidence ids out).

---

## J. Memory for your own chats (the direct competition)

Checked on 2026-10-18, mostly from vendor pages and third-party write-ups. **[3p]** marks a detail found
only in a third-party write-up.

### Built into the chat apps
- **Claude** ([help centre](https://support.claude.com/en/articles/11817273-using-claude-s-memory)):
  - **Memory** carries context from earlier chats into new conversations and Cowork tasks.
  - **Search past chats** works on the web, in Claude Desktop and in the mobile apps, on paid plans (Pro, Max,
    Team, Enterprise). It is retrieval that shows up as a visible tool call. Outside projects it searches all
    chats; inside a project, only that project's chats.
- **ChatGPT:** saved memories and references to chat history. A dated, second-hand comparison says details of
  earlier chats go into every new conversation automatically, while Claude's are tool calls you can see
  ([Simon Willison](https://simonwillison.net/b/9010)). Not checked against OpenAI's current docs.
- **Their strength:** no setup at all.
- **Their limit:** each is locked to its own app. Claude's memory does not reach ChatGPT, Codex or Claude Code
  in another project, and the reverse holds too.

### claude-mem
- Links: [repo](https://github.com/thedotmack/claude-mem). Star counts are [3p]: about 46k in April 2026 and
  83.9k in June 2026 ([Augment](https://www.augmentcode.com/learn/claude-mem-65k-stars),
  [Better Stack](https://betterstack.com/community/guides/ai/claude-mem/)). The licence is listed as both MIT
  and Apache-2.0 by different sources.
- **TL;DR:** a community plugin for Claude Code, installed with one command (`npx claude-mem install`). It
  hooks into each session and records tool use, file reads and edits.
- **How it works:** a background worker summarizes what it recorded using Claude's Agent SDK. Summaries are
  stored in a local SQLite database plus a Chroma vector store. Relevant summaries are pulled into the prompt
  when a session starts, or when a question touches past work.
- **Limits:**
  - Claude Code only.
  - Every write is a model call.
  - It keeps summaries rather than the words that were said, so they can drop or invent details. No source
    spans.
- **For us:** this is the default to beat for "memory in Claude Code". It already has the one-command install
  and automatic capture through hooks that §3.5 plans.

### OpenMemory MCP (Mem0)
- Links: [announcement](https://mem0.ai/blog/introducing-openmemory-mcp) (13 May 2025),
  [docs](https://docs.mem0.ai/openmemory).
- **TL;DR:** a local MCP server with a web UI. One memory is shared across Claude Desktop, Cursor, Windsurf,
  Cline and any other MCP client. The tools are `add_memories`, `search_memory`, `list_memories` and
  `delete_all_memories`.
- **Setup:** runs in Docker. Deleting the container deletes the memory. There is also a hosted version; paid
  Mem0 plans are $19, $79 and $249 a month as of June 2026 [3p]
  ([Hjarni](https://hjarni.com/blog/best-mcp-memory-server)).
- **Limits:** built on Mem0, whose writes are model calls that extract facts (section A). It stores those
  extracted facts, not the original text.

### Basic Memory
- Links: [PyPI](https://pypi.org/project/basic-memory/), [docs](https://docs.basicmemory.com/reference/technical-information).
  Licence AGPL-3.0.
- **TL;DR:** the assistant reads and writes Markdown notes in `~/basic-memory` through MCP. Notes carry
  categorized observations, `[[WikiLink]]` relations and YAML frontmatter.
- **Setup:** `uvx basic-memory mcp`, added to Claude Desktop's config. It also has `sync --watch` and
  importers for Claude and ChatGPT chat exports. A paid cloud offers sync across devices [3p].
- **Limits:** nothing is kept unless the assistant decides to write a note, so ideas mentioned in passing are
  lost. The AGPL licence limits reuse.

### Where cogito-mem stands

| | Built-in (Claude, ChatGPT) | claude-mem | OpenMemory | Basic Memory | **cogito-mem** |
|---|---|---|---|---|---|
| Works across clients | no | Claude Code only | any MCP client | any MCP client | **any MCP client; capture in Claude Code and Codex** |
| Captured without being asked | yes | yes (hooks) | no | no | **yes (hooks), plus imports** |
| Keeps the original words | the chat history | summaries | extracted facts | notes the assistant writes | **yes, with source spans** |
| Model calls per write | vendor-side | yes | yes | the assistant's own | **none** |
| "When was this said?" | not documented | not documented | not documented | file dates | **`valid_at`, time filters, `as_of`** |
| Setup | none | one command | Docker | one command plus a config edit | **one command** |
| Data stays on your machine | no | yes | yes (local mode) | yes | **yes** |

**What we claim:** one memory that works across all your chat tools, keeps your exact words and the date they
were said, never makes a model call, and installs with one command. That is what answers "the idea from a
week ago". It must be findable even though nobody saved it, in whichever tool it came up, with the date
attached.

**What we do not claim:** higher scores than anyone on a benchmark (requirements, decision 17).

**Risks:**
- claude-mem already owns automatic memory for Claude Code alone.
- Built-in memory needs no setup at all.
- Our case rests on working across clients and on keeping the exact words. The demo has to show both: an idea
  from a Codex session found from Claude, quoted exactly and dated.

---

## Cross-cutting findings for MrCogito

1. **Nobody trains the whole memory.** Deployed agent memories are prompted pipelines over text;
   trained memories live inside one model and forget by design; plug-in memories bind to one
   reader. The combination we want — trained fast writer + trained retriever + trained
   consolidation, append-only, served through text — has no published instance we could find.
   Closest pieces: M+ (latent store + co-trained retriever + age tags, retriever finds ~30 %),
   MemoRAG (memory model steering a separate generator), Zep (bi-temporal graph), HippoRAG (graph
   + PageRank multi-hop), Letta sleep-time (offline pass), Memory Decoder (plug-and-play by
   tokenizer), Jev (typed protocol).
2. **The wire to a foreign LLM must be text (or typed JSON).** No latent format is read untrained
   across unrelated model families (F); the latent wins over fair text baselines are a few points.
   Latent stays inside the memory, where it does the addressing and the multi-hop work.
3. **Pull beats push** — in our data (E35 0 % vs E33f 97–100 %) and in the literature (AgentPrune,
   retrieval vs summaries). The memory should answer questions, not broadcast summaries.
4. **Retrievers learn best from the reader's likelihood** (Atlas PDist, REPLUG, AAR), writers from
   a teacher that sees the raw text (Cartridges, xRAG KL stage). Preferences learned with a small
   reader transfer to large ones (AAR) — so a 30M training reader is not a dead end.
5. **Time is solved as data structure, not as reasoning.** Version chains and validity intervals
   exist; using them in multi-hop answers does not (MemoryAgentBench ≤ 28 %). A trained
   order/supersession signal (our E33e rank term) is the open piece.
6. **Latency is not the hard limit; memory and staleness are.** < 1 ms ANN at 100M vectors on CPU;
   full-precision RAM is the cost; a trained writer makes stored keys stale (REALM: 38.2 → 28.7) —
   the scheduled offline pass is the natural place to re-key and rewire.
7. **Bytes vs positions.** Our notes are 256 B per 6 tokens (~43 B/token) vs ~4.2 B/token of raw
   text: the latent store is ~10× *larger* than the text it indexes. Latent memory compresses what
   the **reader attends to** (positions, compute), not storage. Byte compression needs more tokens
   per note or fewer dimensions per note — both on the compression ladder, not quantisation.
