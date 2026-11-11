# One engine for text and vectors? cogito-mem's index against SQLite FTS5 + sqlite-vec, zvec and LanceDB

*Measurements, 11 Nov 2026. Script: [`scripts/engines/bench.py`](../../scripts/engines/bench.py); results:
[`evals/baselines/engines-20261111/`](../../evals/baselines/engines-20261111/). Nothing in `src/` changed.*

**In short.** We asked whether one local engine that keeps the text, the filters and the vectors together
would serve cogito-mem better than its own index. We picked the three embedded engines that fit the install
(SQLite FTS5 with sqlite-vec, zvec, LanceDB) and ran each against cogito-mem on the same 10M-token memory of
LongMemEval-S text, and on all 500 LongMemEval-S questions.

- **Quality does not change.** Each engine indexed exactly the terms cogito-mem's BM25 indexes. zvec and
  LanceDB return the same session ranking as cogito-mem on all 500 questions. FTS5 differs by one question
  (R@5 −0.2 points, 95 % CI −0.6 to 0.0) because its IDF formula differs. Vector search is exact in all of
  them: the same items in the first 10 and 100 (overlap ≥ 0.99).
- **cogito-mem's own index is the fastest at query time.** A hybrid search at 10M tokens takes 4.2 ms
  (median; p95 5.6). zvec takes 5.8 ms (7.8), SQLite 44 ms (65) and LanceDB 63 ms (72).
- **What an engine buys is start-up.** cogito-mem rebuilds its index from the log on every start: 6.5 s at
  10M tokens on this 4-core VM, and it grows with the history. 85 % of that is the pure-Python BM25 build.
  The engines open in 0.06–0.6 s.
- **Saving our own index gets most of that without an engine.** Postings, columns and vectors written to
  `.npy` files open in an estimated 0.9 s instead of 5.0 s (69 MB on disk, no new dependency).
- **The 100M-token stretch is where an engine pays.** At 1M items, exact vector search alone takes 107 ms
  at p95 (the gate is 100 ms for the whole query). zvec's HNSW index answers in 2.0 ms (p95 2.7), with
  recall@100 of 0.999 against exact on clustered synthetic vectors.
- **Recommendation.** Don't replace the index now. Persist it (§6). If the 100M stretch becomes a goal, zvec
  is the engine to adopt, for the vector list first, under the conditions in §7. Leave SQLite FTS5 +
  sqlite-vec and LanceDB out: the first is 10× slower per query and has no ANN index, the second is 15×
  slower and slows down further with every small append.

## 1. How cogito-mem stores and finds things today

**Storage (all under `~/.cogito-mem/`).**

`memory/<namespace>/log.sqlite3`, the source of truth. Triggers refuse UPDATE and DELETE:

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);          -- schema_version = 1
CREATE TABLE log (
    seq        INTEGER PRIMARY KEY,   -- arrival order; readers pick up rows with seq > last seen
    id         TEXT NOT NULL UNIQUE,  -- UUIDv7, sorts by time
    created_at INTEGER NOT NULL,      -- ms, set by the memory (= valid_at on import); as_of filters on it
    valid_at   INTEGER NOT NULL,      -- ms, when it happened; valid_after/valid_before filter on it
    thread_id  TEXT NOT NULL, author TEXT NOT NULL, title TEXT, text TEXT NOT NULL,
    client_ref TEXT,                  -- dedup key, unique per (author, client_ref)
    retracts   TEXT NOT NULL,         -- JSON list of ids this item withdraws
    pieces     TEXT NOT NULL,         -- JSON [[piece_id, start, end, tokens], ...]: spans of ≤ 256 tokens
    imported   INTEGER NOT NULL);
```

`cache/embeddings.sqlite3`, shared by every namespace and safe to delete:

```sql
CREATE TABLE vectors (key BLOB PRIMARY KEY,   -- sha256(model name + "\0" + the exact prompt embedded)
                      vec BLOB NOT NULL)      -- 256 × float16, cut, normalised and rounded
WITHOUT ROWID;
```

**How a fact links to its vector.** Nothing joins on an id. The link is the content: for each piece the
memory rebuilds the prompt it embedded, hashes it, and looks it up. With the defaults (`doc_author`,
`doc_context="previous"`) a reply is embedded together with the end (≤ 1,000 characters) of the message it
answers:

```
title: none | text: user: Let's call the staging server acorn.\n\nassistant: Got it: the staging server is acorn.
```

So a text embedded once is never embedded again, in any namespace. A new model or prompt setting gets new
keys by itself. The cost is that every start recomputes every prompt and its sha256 before the vectors are
back.

**In RAM, per namespace (`store.Namespace`), all rebuilt from the log on open:**

- the messages, with their text;
- one numpy column per piece: message, span, tokens, `created`, `valid`, kind, thread code, author code,
  `retracted` (derived from later `retracts`) and has-vector;
- the vectors as an `n × 256` float32 matrix;
- the BM25 postings, one `array('i')` of (row, tf) pairs per term, over `author: title\ntext`.

**Append** (`Memory._append` → `Namespace.append`):

1. Split the text into pieces of at most 256 tokens, at paragraphs, then sentences.
2. In one `BEGIN IMMEDIATE` transaction, write the log row, with UUIDv7 ids and a strictly increasing
   `created_at`.
3. Index it: the columns, plus BM25, so it is searchable by keyword when the call returns.
4. In the background: build the prompt, look it up in the cache, have llama-server embed what is missing
   (EmbeddingGemma 2), then store the vector.

**Query** (`Memory._query` → `candidates` → `Namespace.search` → `fill`):

1. `as_of` is the request's, else max(now, the latest `created_at`).
2. Embed `task: search result | query: {text}` (an LRU cache of 256 queries).
3. Mask the rows on `created ≤ as_of < retracted` and the thread, author, kind and valid filters (numpy
   booleans).
4. Rank two lists, each read to `max(100, 3 × top_k)` items:
   - the exact dot product with the masked vectors;
   - BM25 over the query's terms, with function words dropped from the query only.
5. Fuse them by reciprocal rank (k = 60), scaled so that first in both lists scores 1.
6. Fill: items in score order until `top_k` or `max_tokens` is reached.
7. The recall hook then keeps only items scoring ≥ 0.6 that share enough of the prompt's words.

## 2. What an engine would have to keep

Searchable by keyword the moment `append` returns. Searchable by meaning once the background embedding
lands. Time travel: `as_of` on `created`, retractions, and windows on `valid`. Thread and author filters. Two
separate ranked lists, because cogito-mem fuses them itself. fp16 vectors, searched exactly unless an index
earns its error. Several processes opening one namespace (the service, `install`, `mcp --in-process`, the
Python API). And the install: today it is `cogito-mem` plus numpy, with checksums in the plugin's `uv.lock`,
on macOS, Linux and Windows.

## 3. The candidates

| Engine (version) | Text search | Vectors | Filters | Processes | Install | Run here |
|---|---|---|---|---|---|---|
| **SQLite FTS5 + sqlite-vec** (0.1.9) | BM25 (FTS5, in Python's sqlite3) | exact only, float32 | SQL, metadata columns in KNN | many (SQLite) | 0.3 MB wheel, no deps; needs `enable_load_extension` (uv's managed CPython has it) | yes |
| **zvec** (0.8.1) | BM25-style FTS, whitespace tokenizer | flat, HNSW, IVF, DiskANN; fp16 | expressions on inverted indexes | **one**: a second process cannot open the collection, even read-only | 18.6 MB wheel (44 MB installed), numpy only | yes |
| **LanceDB** (0.41.0) | native BM25 FTS | flat, IVF-PQ, HNSW; fp16 | SQL prefilter | many | lancedb + pyarrow: ~350 MB installed | yes |
| Lucene (PyLucene, Pyserini) | BM25 | HNSW | yes | many | a JVM | no: no JVM in a `uvx` install |
| Tantivy (0.27) | BM25 | none | yes | one writer | 9.5 MB wheel | no: text only, so not "one engine" |
| Milvus Lite (3.2) | BM25 as sparse vectors, in pure Python | FAISS | yes | one per data folder | grpcio, pyarrow, faiss | no: no fp16, single process, pure-Python BM25 |
| Qdrant, Weaviate, Chroma, Infinity, seekdb | — | — | — | — | a server, a downloaded binary, or onnxruntime/torch-sized deps | no |

## 4. The test

- **Memory.** 10,001,367 tokens: 69,948 items from 41,357 messages, 4,005 deduplicated LongMemEval-S
  sessions, loaded through cogito-mem's own `append` (`import`).
- **Vectors.** Random, seeded by a hash of the prompt, stored through the real embedding cache. Every engine
  searches vectors exactly here, so random vectors time the search without changing what it finds.
- **Same input everywhere.** Each engine gets each item's BM25 text as cogito-mem's own terms, joined by
  spaces, under a whitespace tokenizer, and is queried with cogito-mem's query terms ORed. So any ranking
  difference comes from the engine.
- **Queries.** The 500 LongMemEval-S questions, 1,000 per lane with the "all" filter and 500 each with the
  "one thread" and "older 30 %" filters. Pool 100; the query's embedding is left out (the same for all).
- **Machine.** A 4-core VM (Intel Xeon @ 2.1 GHz), CPython 3.12.3, SQLite 3.45.1, numpy 2.5.4, BLAS on one
  thread as `cogito-mem serve` sets it. Files were in the page cache for every engine (a warm start).
- **Isolation.** Each speed run uses a private copy, opened in a fresh process. RAM is the process's private
  memory (USS) after the queries, minus what it held before opening.

## 5. Results

### 5.1 Quality: LongMemEval-S, all 500 questions, the keyword list

Session recall of the list each engine returns (`as_of` = question date; `top_k` 300, no budget):

| | R@1 | R@5 | R@10 | NDCG@10 | turn NDCG@10 | R@5 vs cogito-mem |
|---|---|---|---|---|---|---|
| cogito-mem | 81.4 | 91.0 | 94.0 | 82.7 | 58.0 | — |
| SQLite FTS5 | 81.8 | 90.8 | 94.0 | 82.8 | 58.2 | −0.2 (−0.6 to 0.0), 0 better, 1 worse |
| zvec | 81.4 | 91.0 | 94.0 | 82.7 | 58.0 | 0.0, no question differs |
| LanceDB | 81.4 | 91.0 | 94.0 | 82.7 | 58.0 | 0.0, no question differs |

With no cutoff (LongMemEval's own protocol) it is the same picture: R@5 95.0 for cogito-mem, zvec and
LanceDB, and 94.8 for FTS5. zvec and LanceDB score BM25 as cogito-mem does, with log(1 + …) IDF. FTS5 drops
the "1 +" and floors at zero the IDF of a term found in more than half the items.

### 5.2 Same results? (10M tokens, the first 200 queries per lane)

Overlap of each engine's first 10 / 100 with cogito-mem's, and the share of identical top-10 orders:

| | SQLite | zvec | LanceDB |
|---|---|---|---|
| keyword, all | 0.993 / 0.992, same order 69 % | 1.000 / 0.999, 93 % | 1.000 / 1.000, 89 % |
| vector, all | 1.000 / 1.000, 99 % | 1.000 / 1.000, 94 % (fp16 arithmetic) | 1.000 / 1.000, 100 % |
| hybrid, all | 0.993 / 0.996, 86 % | 0.998 / 1.000, 94 % | 0.999 / 1.000, 94 % |

The thread and window filters agree at least as well (`parity.json`).

### 5.3 Speed, start-up, memory and appends (10M tokens)

Median / p95, in ms unless marked:

| | cogito-mem | SQLite FTS5 + sqlite-vec | zvec | LanceDB |
|---|---|---|---|---|
| ready after start (both lists answer) | **6.5 s** | 0.06 s | 0.12 s | 0.57 s (+0.9 s import) |
| hybrid, all visible | **4.2 / 5.6** | 44 / 65 | 5.8 / 7.8 | 63 / 72 |
| hybrid, one thread | **0.6 / 1.0** | 11 / 17 | 1.3 / 1.8 | 15 / 19 |
| hybrid, older 30 % | 4.2 / 5.4 | 23 / 34 | 4.2 / 5.4 | 26 / 31 |
| keyword list, all | **0.6 / 1.0** | 8.6 / 21 | 1.6 / 2.3 | 13 / 16 |
| vector list, all | **3.2 / 4.4** | 33 / 47 | 3.9 / 5.3 | 52 / 60 |
| RAM (USS) | 204 MB | **114 MB** | 176 MB | 663 MB |
| append one message (keyword-searchable on return) | 1.0 / 2.1 | 0.1 / 0.6 | 0.7 / 1.2 | 5.1 / 7.9 |
| store its vector | in the background | 0.1 / 0.2 | 0.6 / 1.2 (an update) | 24 / 44 (an update) |
| hybrid after those 200 appends | 4.6 / 6.1 | 45 / 63 | 13 / 16 | 106 / 118 |
| disk | 60 MB log + 50 MB cache | +98 MB | +174 MB | +67 MB |
| build from the log (one-off) | 5.1 s on every open | 3.4 s | 38 s | 3.6 s |

Where the start-up goes: `Namespace` opens in 5.1 s, and 85 % of that is `BM25Index.add`, the pure-Python
postings build. Then the vectors come back from the cache in 1.4 s.

### 5.4 Live appends over time

Capture appends a few items per turn, so a day of work is hundreds of small writes. Hybrid median / p95
after each 500 appends, each followed by its vector:

| appended | 0 | 500 | 1,000 | 1,500 | 2,000 | after compaction |
|---|---|---|---|---|---|---|
| cogito-mem | 4.6 / 6.2 | 4.4 / 5.8 | 4.5 / 6.8 | 4.8 / 6.8 | 4.9 / 6.3 | (none needed) |
| SQLite | 44 / 62 | 48 / 72 | 50 / 71 | 46 / 66 | 48 / 71 | (none needed) |
| zvec, insert then update the vector | 6.0 / 7.7 | 13.7 / 17.0 | 15.0 / 18.3 | 17.0 / 20.7 | 18.1 / 22.3 | 12.6 / 14.7 (`optimize`, 9.2 s) |
| zvec, inserted once with its vector | 6.8 / 8.7 | 7.5 / 9.3 | 8.6 / 11.2 | 9.1 / 11.1 | 10.6 / 13.3 | 6.5 / 8.4 (`optimize`, 8.4 s) |

LanceDB was already at 106 ms after 200 appends; `optimize` (1.0 s) brought it back to 67 ms. Also found:
in zvec 0.8.1, a filtered FTS query that asks for no output fields fails while unoptimised rows exist
(`ExecBatch::ToRecordBatch mismatching schema size`). Asking for one field avoids it.

### 5.5 The 100M-token stretch: 1M items, vector list only

Clustered unit vectors (2,000 centres), fp16-rounded; filter `created ≤ as_of` with 70 % visible; 500
queries:

| | median | p95 | recall@10 / @100 vs exact | build | size |
|---|---|---|---|---|---|
| numpy, exact (today's code) | 89 ms | **107 ms** | — | — | 977 MB RAM (float32) |
| sqlite-vec, exact | 373 ms | 443 ms | 0.999 / 0.999 | 53 s | 1,009 MB |
| zvec flat, exact | 67 ms | 81 ms | 1.000 / 1.000 | 29 s | 566 MB |
| zvec HNSW (m 16, ef 100) | **2.0 ms** | **2.7 ms** | 1.000 / 0.999 | 226 s | 716 MB |

Synthetic clusters are kinder to a graph index than real embeddings may be, so recall must be checked on
EmbeddingGemma vectors before relying on it.

## 6. No engine: persist the index cogito-mem already builds

The query path is already the fastest of the four. What hurts is rebuilding it on every start. Saving the
BM25 postings (one int32 array with per-term offsets), the lengths and the fp16 vectors next to the log, then
loading them with `mmap`, measured at 10M tokens:

| | time |
|---|---|
| open today | 5.0 s, plus 1.4 s for the vectors |
| open with BM25 left out (the messages and columns) | 0.59 s |
| load the saved postings and the 69,948 vectors | 0.33 s |
| **estimated open with a snapshot** | **0.9 s, vectors included** |

The snapshot would carry the log `seq` it covers. On open, only log rows past it would be indexed, so it
never has to be exact: deleting it costs one rebuild, as deleting the embedding cache does now. Holding the
message text in SQLite rather than in RAM would cut both the remaining 0.6 s and the RAM. Neither is built
yet.

## 7. When to adopt an engine, and which

- **zvec**, if the 100M-token stretch becomes a goal, starting with the vector list (HNSW). It is the only
  one that matches cogito-mem's speed. It needs only numpy, keeps fp16 and survives a crash through its WAL.
  The conditions:
  - the service owns the collection, because nothing else can open it while it runs;
  - an item goes in only once its vector exists, with the newest items searched from a small in-RAM tail
    until then, because updates slow it down for good;
  - `optimize` runs when the service is idle (about 9 s at 10M tokens);
  - the version is pinned, given the bug above in a 0.x release;
  - the log stays the truth, so the collection can always be rebuilt (38 s at 10M tokens).
- **SQLite FTS5 + sqlite-vec** is the best fit operationally: the same file, one transaction with the log,
  many processes, a 0.3 MB wheel and the least RAM. But it is 10× slower per query at 10M tokens and has no
  ANN index for 100M. Its FTS5 half alone could replace the Python BM25 rebuild, if a snapshot (§6) ever
  proves fragile.
- **LanceDB**: no. It is the slowest per query, slows down with every small append until compacted, and
  brings ~350 MB of dependencies.

## 8. Reproduce

```bash
pip install sqlite-vec zvec lancedb psutil   # in a venv with cogito-mem installed
scripts/engines/run_all.sh "$(which python)" longmemeval_s_cleaned.json runs/   # fill, build, speed, parity, 1M scale
python scripts/engines/bench.py quality  --data longmemeval_s_cleaned.json --out runs/quality.json
python scripts/engines/bench.py churn    --root runs/m10 --engine zvec [--with-vectors]
python scripts/engines/bench.py snapshot --root runs/m10
```

Limits of this run: one machine, CPU only, warm page cache, random vectors (exact engines are unaffected;
HNSW recall needs real ones). macOS and Windows were not tried.
