# Memory API notation, faithful digests, surprise, EmbeddingGemma

Scout notes checked against official docs, arXiv and GitHub on **2026-10-18**. They back the API names and
the stage choices in [`../requirements.md`](../requirements.md). Unverified items are listed at the end.
The broader survey of memory systems is in [`agent_memory_systems.md`](agent_memory_systems.md).

**What changed since that survey (17 Oct):**
- **Mem0:** the docs now serve a v3 API.
- **Zep:** search is now split into per-type calls keyed by `graph_uuid`.
- **OpenTelemetry:** its GenAI conventions now name memory operations.
- **EmbeddingGemma 2:** released on 2026-10-06.

## 1. JSON field names in memory APIs

**API changes:**
- **Mem0:** documents `POST /v3/memories/search/` and `/v3/memories/add/` ([search](https://docs.mem0.ai/api-reference/memory/search-memories), [add](https://docs.mem0.ai/api-reference/memory/add-memories)). The v2 filter syntax is still documented ([v2 filters](https://docs.mem0.ai/platform/features/v2-memory-filters)).
- **Zep:** `graph.search` is replaced by `graph.search_edges`, `search_nodes`, `search_episodes` and `graph.get_context` ([docs](https://help.getzep.com/searching-the-graph)).

| System | Request keys | Hit / record keys | Score | Time | Scoping | Paging |
|---|---|---|---|---|---|---|
| Mem0 v3 | Add: `messages`, `metadata`, `infer`, `timestamp` (Unix seconds; backdates `created_at`), `expiration_date`. Search: `query`, `filters` (AND/OR/NOT; `gte`/`lte` on `created_at`/`updated_at`), `top_k` ≤1000, `threshold` (default 0.1), `rerank`, `reference_date`, `show_expired` | `id`, `memory`, `created_at`, `updated_at`, `expiration_date`, `metadata`, `categories` | `score` in [0,1], plus `score_breakdown{semantic,bm25,entity}` | ISO | `user_id`, `agent_id`, `app_id`, `run_id` (inside `filters`) | — |
| Zep / [Graphiti](https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py) | `graph_uuid`, `query`, `reranker` (`rrf`, `mmr`, `cross_encoder`…), `filters.date_filters.any_of[].all_of[]{field,operator,value}` | Edge ([ref](https://help.getzep.com/v2/sdk-reference/graph/edge/get-edge)): `uuid`, `name`, `fact`, `source_node_uuid`, `target_node_uuid`, `episodes`, `attributes`, `created_at`, `valid_at`, `invalid_at`, `expired_at` | `score`; `relevance` [0,1] with `cross_encoder` | RFC 3339 | `graph_uuid` / `group_id` | `page_size` ≤50, `cursor` |
| [Letta](https://docs.letta.com/api/resources/agents/subresources/passages/methods/search/index.md) | `query`, `tags`, `tag_match_mode`, `top_k`, `start_datetime`, `end_datetime` | `results[]{id,content,timestamp,tags}` | — | ISO | `agent_id` / `archive_id` | `top_k` |
| [OpenAI vector store](https://developers.openai.com/api/reference/resources/vector_stores/methods/search) | `query`, `filters`, `max_num_results` (1–50), `ranking_options{ranker,score_threshold}`, `rewrite_query` | `data[]{file_id,filename,score,attributes,content[{type,text}]}` | `score`, range not documented | — | store | `has_more`, `next_page` |
| [Anthropic memory tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) | `command` ∈ `view`/`create`/`str_replace`/`insert`/`delete`/`rename`, with `path`, `file_text`… | plain-text `tool_result` | — | — | `/memories` | `view_range` |
| AWS AgentCore | [CreateEvent](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_CreateEvent.html): `actorId`, `sessionId`, `eventTimestamp`, `payload`, `branch`, `clientToken`, `metadata`. [RetrieveMemoryRecords](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_RetrieveMemoryRecords.html): `namespace`, `searchCriteria{searchQuery,topK,…}`, `maxResults` | `memoryRecordSummaries[]{memoryRecordId,content,memoryStrategyId,namespaces,metadata,createdAt,timestamp,score}` | `score`, no range given | `createdAt` = written; `timestamp` = source time | namespaces built from `{actorId}`/`{sessionId}`; strategies: semantic, summary, user preference, episodic | `nextToken` |
| Google Memory Bank | [generate](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/generate-memories) / [retrieve](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/fetch-memories): `scope`, `similarity_search_params{search_query,top_k}`, `config.filter` | `memory{name,fact,…}`, `distance` | Euclidean `distance`, lower is better | ISO | `scope` dict | pager |
| [Supermemory v4](https://supermemory.ai/docs/api-reference/search/search-memory-entries) | `q`, `containerTags`, `threshold`, `limit`, `rerank`, `filters` | `results[]{id,memory\|chunk,metadata,updatedAt,similarity,version,…}` | `similarity` [0,1] | — | `containerTags` | `limit` |
| [LangGraph store](https://docs.langchain.com/oss/python/langgraph/stores) | `put(namespace,key,value)`, `search(namespace_prefix,query,filter,limit,offset)` | `namespace`, `key`, `value`, `created_at`, `updated_at`, `score` | `score` | datetime | tuple namespace | `limit`, `offset` |

**Vector databases:**
- **[Pinecone](https://docs.pinecone.io/reference/api/latest/data-plane/query):** `matches[{id,score,values,metadata}]`.
- **[Elasticsearch](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/paginate-search-results):** `hits.hits[{_id,_score,_source}]`.
- **[Cohere rerank](https://docs.cohere.com/reference/rerank):** `results[{index,relevance_score}]`, with scores in [0,1] that the docs call "not ratios".

**Standards an append event can borrow from:**
- **[CloudEvents 1.0](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md):** requires `id`, `source`, `specversion` and `type`; `time`, `subject` and `data` are optional. `source` + `id` must be unique.
- **[PROV-O](https://www.w3.org/TR/prov-o/):** `prov:wasAttributedTo`, `prov:generatedAtTime`, `prov:wasDerivedFrom`, `prov:invalidatedAtTime`.
- **[ActivityStreams 2.0](https://www.w3.org/TR/activitystreams-vocabulary/):** `id`, `type`, `actor`, `object`, `published`, `content`, `summary`, `context`, `inReplyTo`.
- **Spans in a source, [W3C Web Annotation](https://www.w3.org/TR/annotation-model/):** `TextPositionSelector{start,end}` counts code points with `end` exclusive; `TextQuoteSelector{exact,prefix,suffix}` quotes the text.
- **OpenTelemetry GenAI ([repo](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md), still in development):**
  - operations `search_memory`, `create_memory`, `update_memory`, `delete_memory`;
  - attributes `gen_ai.memory.store.id`, `gen_ai.memory.record.id`, `gen_ai.memory.query.text`;
  - `gen_ai.conversation.id` for a session or thread.
- **Pagination, [AIP-158](https://github.com/aip-dev/google.aip.dev/blob/master/aip/general/0158.md):** `page_size`, `page_token`, `next_page_token`.
- **SQL:2011:** `FOR SYSTEM_TIME AS OF` for "as the database stood at that moment" ([Kulkarni & Michels 2012](https://sigmodrecord.org/2012/09/30/temporal-features-in-sql2011/)).

**Which name the majority use:**

| Concept | Names seen | Majority |
|---|---|---|
| id | `id`; `uuid`, `memoryRecordId`, `_id`, `key` | **`id`** |
| text | `content`, `memory`, `fact`, `data`, `value` | **`content`** as a container, **`text`** as the leaf |
| write time | `created_at`, `createdAt`, `published`, `generatedAtTime` | **`created_at`** |
| event / valid time | `valid_at`/`invalid_at` (Zep), `timestamp` (AWS, Letta), `time` (CloudEvents) | none; only Zep and AWS keep both times |
| author | `user_id`/`agent_id`, `actorId`, `attributedTo`, `source` | `user_id` / `agent_id` |
| session | `run_id`, `session_id`, `gen_ai.conversation.id`, `contextId` (A2A) | `session_id` |
| partition | `namespace`, `scope`, `containerTags`, `group_id` | **`namespace`** |
| score | `score` (6 systems), `_score`, `relevance_score`, `similarity`, `distance` | **`score`** |
| source span | `episodes`, `file_id`, `documents` | no memory API exposes character spans; W3C selectors are the only standard |
| count | `top_k`/`topK` in 5 systems | **`top_k`** |

## 2. Faithful digests

- **Copying is not automatically faithful.** In [ACL 2023](https://aclanthology.org/2023.acl-long.120), 30 % of 1,600 extractive summaries from 16 systems had at least one coreference or discourse error.
- **Atomic facts:**
  - [FActScore](https://arxiv.org/abs/2305.14251) splits text into atomic facts; its automatic estimator is within 2 % of human scores.
  - [FineSurE](https://aclanthology.org/2024.acl-long.51) scores faithfulness, completeness and conciseness at the level of key facts.
- **Citation:** in [SummHay](https://arxiv.org/abs/2407.01370), humans reach 56 % on coverage plus citation, and long-context LLMs without a retriever stay under 20 %.

Fact-checkers, by average balanced accuracy on [LLM-AggreFact](https://llm-aggrefact.github.io/) (50 = chance):

| Checker | Size | Accuracy | Notes |
|---|---|---|---|
| [HHEM-2.1-Open](https://huggingface.co/vectara/hallucination_evaluation_model) | flan-t5-base | 76.55 (AggreFact-SOTA) | about 1.5 s per 2k-token input on CPU |
| MiniCheck-Flan-T5-L ([EMNLP'24](https://arxiv.org/abs/2404.10774)) | 0.8B | 75.0 | |
| FactCG-DeBERTa-L | 0.4B | 75.6 | |
| Bespoke-MiniCheck-7B | 7B, CC BY-NC | 77.4 | top of the board |
| Granite Guardian 3.3 | 8B (2B/5B variants exist) | 76.5 | |
| [AlignScore](https://aclanthology.org/2023.acl-long.634) | 355M | on par with GPT-4-based metrics | |
| [LettuceDetect](https://arxiv.org/abs/2502.17125) | ModernBERT, 8k context | RAGTruth F1 79.22 | marks the unsupported spans |

**Small models invent things when summarizing** ([Vectara leaderboard](https://github.com/vectara/hallucination-leaderboard), judged by HHEM-2.3 on more than 7,700 articles, 16 Oct 2026):

| Model | Hallucination rate |
|---|---|
| Qwen3-4B | 5.7 % |
| Gemma-3-4B | 6.4 % (answered only 67.3 % of the time) |
| Ministral-3B-2410 | 7.3 % |
| Phi-4-mini | 23.5 % |
| Best overall (32B) | 1.8 % |

**Cost of digesting a 5k-token document with a 4B model** (arithmetic estimate, not measured): about 0.1 s to read it on an H100, plus 2–3 s to write a 300-token digest.

## 3. Surprise and novelty

- **Surprise per token:**
  - [EM-LLM](https://arxiv.org/html/2407.09450v3) (ICLR 2025) measures surprise as −log P(x_t | x<t) and starts a new event where it exceeds μ + γσ.
  - [Titans](https://arxiv.org/abs/2501.00663) uses the gradient of a memory loss as its surprise signal.
- **Surprise across a document:**
  - Summaries are less surprising than their sources ([2309.06009](https://arxiv.org/abs/2309.06009)).
  - [Selective Context](https://arxiv.org/abs/2310.06201) drops text with low self-information.
  - Peyrard ([ACL 2019](https://aclanthology.org/P19-1101/)) defines redundancy, relevance and informativeness.
- **Novelty against the existing store,** the closest to "surprising for this memory": [SAGE](https://arxiv.org/abs/2605.30711) ([repo](https://github.com/swang1024/SAGE)).
  - It scores each candidate fact with a von Mises–Fisher density over the memory's embeddings.
  - It adds clearly new facts, skips clearly redundant ones, and sends only the uncertain ones to an LLM.
  - It beats Mem0 on LoCoMo across 7 open models and writes at a 3.4× lower cost.
- **Update summarization** ([TAC 2008](https://tac.nist.gov/publications/2008/presentations/TAC2008_UPDATE_Sutler.pdf)) summarizes set B for a reader who has already seen set A. No successor from the LLM era was found.
- **No benchmark checks whether a summary keeps the surprising facts.** The closest are key-fact completeness metrics ([UniSumEval](https://arxiv.org/abs/2409.19898), [MSumBench](https://arxiv.org/abs/2506.00549)). We have to build this test ourselves.

## 4. EmbeddingGemma, and retrieval-only benchmarks

| | EmbeddingGemma ([card](https://huggingface.co/google/embeddinggemma-300m), [paper](https://arxiv.org/abs/2509.20354)) | EmbeddingGemma 2 ([card](https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2)) |
|---|---|---|
| Released | 2025-09-04, Gemma licence | 2026-10-06, Apache 2.0 |
| Size | 300M | 740M in all; 270M for text |
| Context | 2,048 tokens | 8,192 tokens |
| Dimensions | 768, cut to 512 / 256 / 128 | 768, cut to 512 / 256 / 128 |
| MTEB Multilingual at 768 / 512 / 256 / 128 | 61.15 / 60.71 / 59.68 / 58.23 | 61.36 / 61.17 / 60.41 / 57.89 |
| Quantized weights | Q8 60.93, Q4 60.62 | not reported |
| llama.cpp build | [ggml-org/embeddinggemma-300M-GGUF](https://hf.co/ggml-org/embeddinggemma-300M-GGUF) | [ggml-org/embeddinggemma-2-GGUF](https://hf.co/ggml-org/embeddinggemma-2-GGUF) (published on release day) |

- **Prompts:** queries use `task: search result | query: ` and documents use `title: none | text: `. Neither model supports float16.
- **Binary or int8 output vectors:** neither model publishes numbers. On other models binary keeps 75–93 % of retrieval quality ([HF blog](https://huggingface.co/blog/embedding-quantization)), so it has to be measured.
- **Chunks that carry their document's context:**
  - Late chunking: [2409.04701](https://arxiv.org/abs/2409.04701).
  - ConTEB / InSeNT: [2505.24782](https://arxiv.org/abs/2505.24782).
  - [Voyage context-3](https://blog.voyageai.com/2025/07/23/voyage-context-3/): +6.8 % over Anthropic's contextual retrieval.
  - [Anthropic contextual retrieval](https://www.anthropic.com/news/contextual-retrieval): top-20 failures fall from 5.7 % to 1.9 % with context, BM25 and reranking.
- **Adapters on the query side only:**
  - [Chroma](https://research.trychroma.com/embedding-adapters): up to +70 % from about 1,500 pairs (vendor claim).
  - [ERA](https://arxiv.org/abs/2604.03403): +12 % nDCG@10.
- **Embeddings that decode back to text:**
  - [vec2text](https://arxiv.org/abs/2310.06816) recovers 92 % of 32-token inputs exactly.
  - [xRAG](https://arxiv.org/abs/2405.13792) feeds one retriever vector to a frozen LLM.
  - [LLM2Vec-Gen](https://arxiv.org/abs/2603.10913) trains embeddings with a reconstruction loss.

Memory benchmarks that can score retrieval with no judging model:

| Benchmark | Scored without a judge? |
|---|---|
| [LongMemEval](https://github.com/xiaowu0162/LongMemEval) | **Yes.** Recall@k and NDCG@k at k = 5 / 10, by session (`answer_session_ids`) or turn (`has_answer`), via `run_retrieval.sh`; the 30 abstention questions are excluded. Best on the M split: R@5 0.732, R@10 0.862 ([paper](https://arxiv.org/html/2410.10813)) |
| [LoCoMo](https://arxiv.org/html/2402.17753) | **Yes.** Evidence turn ids are given. The public repo holds 10 of the 50 conversations |
| [MemoryAgentBench](https://arxiv.org/html/2507.05257) | No (end-task accuracy only) |
| [BEAM](https://arxiv.org/html/2510.27246) | No (scored by an LLM judge) |

## Not verified

- Google Memory Bank's `simple_retrieval_params`.
- AgentCore's default namespace templates.
- SQL:2011 syntax details.
- The AIP-132 and AIP-148 field names.
- Score ranges for OpenAI and AWS.
- The late-chunking gain of about 3 %.
- The EmbeddingGemma 2 numbers, which come only from Google's card.
- The 5k-token digest latency, which is an estimate.
