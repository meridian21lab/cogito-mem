# Rewriting Cogi in Rust: what it would buy, measured

*Measurements, 11 Nov 2026. Prototype: [`scripts/rust_probe/`](../../scripts/rust_probe/) (930 lines of Rust).
Results: [`evals/baselines/rust-probe-20261111/`](../../evals/baselines/rust-probe-20261111/). Nothing in
`src/` changed.*

*Decision, 12 Nov 2026: no Rust rewrite. This was an experiment. It is kept on the branch
`cogi-rust-experimental` and is not to be merged into `main`.*

**In short.** We built a Rust version of the two parts where speed could matter: the hook that runs with
every prompt, and the core that opens the log and ranks. We checked both against Python on the 10M-token
memory from [`search_engines_20261111.md`](search_engines_20261111.md), then timed them.

- **It returns the same results.** The Rust core finds all 69,948 vectors by rebuilding each prompt's
  sha256 key, and returns the same top 10 in the same order as Python for all 200 checked queries on each
  list. The Rust hook prints the same 9 lines as the Python hook.
- **The hook is where Rust wins: 160 ms → 46 ms per prompt**, launched through `uvx` as the plugin directory
  requires. But a Python hook with fewer imports takes 76 ms. So Rust's own share of the gain is about 30 ms.
- **Start-up: 6.2 s → 1.4 s.** The index snapshot from the engines note gets Python to an estimated 0.9 s.
- **Queries and memory: no gain.** A hybrid query takes 3.6 ms in both, and RAM is the data, not the
  interpreter.
- **Download: 3 MB instead of 5–17 MB**, out of about 330 MB on first start. The 310 MB model and llama.cpp
  stay, and so does the Python interpreter that `uvx` needs.
- **The directory does not block Rust**, as long as the binary keeps arriving through PyPI behind the same
  `uvx cogito-mem==<version>` command. Binaries inside the plugin folder are not a route (§3).
- **Recommendation: don't rewrite.** Trim the hook's imports and save the index, both in Python. That gets
  most of the measured gain for a fraction of the work. §5 lists what would change this.

## 1. What was built and how it was checked

- **`cogi-hook`** (0.5 MB): the `UserPromptSubmit` path of `cogito-mem recall claude-code` with the default
  `hybrid` design. It makes the same two queries to the local service, applies the same score and
  shared-word gates, and writes the same pointer lines, seen file and ledger line. Standard library plus
  `serde_json`.
- **`cogi`** (5.9 MB): opens the same `log.sqlite3` and builds what `Namespace` builds: messages, columns,
  BM25 postings with cogito-mem's terms, and the vectors from the same embedding cache by the same keys.
  It ranks as `Namespace.search` does (BM25, exact dot product, reciprocal rank fusion) and can serve
  `op: query` over HTTP. To make its size honest it also links what a full Cogi needs: bundled SQLite, a
  TLS client for downloads, a regex engine for redaction, an HTTP server.

One x86-64 build for every machine: AVX2 is chosen when the program runs, as numpy's BLAS does. Built with
`opt-level 3`, fat LTO, stripped.

Not built: the MCP server, capture's transcript parsing, the installer, running llama-server, appends.
None is a hot path, but all would have to be ported.

## 2. Results

Machine: 4-core VM (Intel Xeon @ 2.1 GHz), uv 0.11.32, CPython 3.12.3. Median / p95.

### 2.1 The hook, once per prompt (50 warm runs, whole process)

| | against the Python service | against the Rust service |
|---|---|---|
| `uvx cogito-mem==0.3.0 recall claude-code` (today) | **160 / 194 ms** | — |
| the same without `uvx` | 129 / 155 ms | 132 / 169 ms |
| Python hook with few imports, through `uvx` | 76 / 85 ms | — |
| the same without `uvx` | 40 / 53 ms | — |
| Rust hook through `uvx` | **46 / 60 ms** | 36 / 60 ms |
| Rust hook, called directly | 9.3 / 10.9 ms | 3.0 / 4.8 ms |

- `uvx` alone costs about 36 ms in front of a native binary (`uvx ruff==0.14.4 --version` 39 ms, the same
  binary directly 2.9 ms). The directory requires a pinned package launcher (§3), so this is the floor for
  any hook, in any language.
- Of today's 129 ms without `uvx`, the interpreter takes 18 ms and the two queries 13 ms. Most of the rest
  is imports: `urllib.request` with `http.client`, `email` and `ssl` (about 20 ms), then `dataclasses`,
  `logging`, `argparse` and the modules that pull them in.
- The "few imports" hook ([`lean_hook.py`](../../scripts/rust_probe/lean_hook.py)) makes the same two
  queries and applies the same gates with `json`, `socket` and `re`. It does not write the pointer lines,
  the seen file or the ledger. That work is cheap next to the imports, but it makes 76 ms a lower bound,
  not a finished hook.

### 2.2 The core (10M tokens, 69,948 items)

| | Python (numpy) | Rust |
|---|---|---|
| open the log and build the index | 5.08 s | 0.85 s |
| ready, vectors included | **6.17 s** | **1.41 s** |
| keyword list | 0.52 / 0.90 ms | 0.17 / 0.43 ms |
| vector list (exact, float32) | 2.87 / 3.35 ms | 3.34 / 3.93 ms |
| hybrid | 3.60 / 4.42 ms | 3.60 / 4.43 ms |
| hybrid over the vectors as stored (16 bits) | — | 2.51 / 3.09 ms |
| RAM for this memory | 218 MB | 238 MB with both vector copies; about 170 MB with the 16-bit one alone (computed, not run) |
| RAM of the service with no vectors loaded | 180 MB | 136 MB |
| same top 10, in order, as Python (200 queries) | — | keyword 100 %, vector 100 %, hybrid 100 % |

numpy's BLAS is already as fast as hand-written AVX2. Today the query's embedding in llama-server costs
more than the search (requirements §15.19), and Rust does not touch that. Searching the 16-bit vectors
directly is the one thing numpy cannot do, and it would halve the vectors' RAM (about 490 MB instead of
977 MB at 1M items).

### 2.3 Size

| | Python today | Rust prototype |
|---|---|---|
| our wheel | 158 KB, one for every platform | 3.15 MB, one per platform (5.9 MB + 0.5 MB of binaries) |
| dependencies downloaded | numpy: 5.4 MB (macOS arm64), 16.7 MB (Linux x86-64), 12.6 MB (Windows) | none |
| in uv's cache after the first run (Linux x86-64) | 59 MB | 6.5 MB |
| dependencies compiled in | — | 112 crates in `Cargo.lock` |
| Python interpreter | needed | still needed: `uvx` makes a venv even for a binary wheel |
| llama.cpp and the 310 MB model | needed | needed |

The first start downloads about 330 MB either way. A full Cogi in Rust would be larger than the prototype;
7–10 MB is an estimate, not a measurement.

## 3. The plugin directory

From the directory's [pre-submission checklist](https://claude.com/docs/plugins/pre-submission-checklist)
and the [plugins reference](https://code.claude.com/docs/en/plugins-reference), read on 11 Nov 2026. The
checklist covers the automated checks only. The Anthropic Software Directory Policy also applies and was
not read for this note.

**What works: a native wheel on PyPI behind the same command.** maturin builds wheels that hold a binary
(`ruff` and `uv` ship this way), and `uvx cogito-mem==0.3.0 recall claude-code` runs one exactly as it runs
Python. `plugin.json`, `hooks.json` and `server.json` would not change, and `uv.lock` would list one wheel
per platform with its hash. The checklist's verdict stays what it is today: a pinned launcher passes the
blocking check and "is still held, because the package's own dependencies resolve at install time". With
numpy gone there would be no dependencies to resolve.

**What does not work: binaries in the plugin folder.**

- "keep every file in the plugin folder under 5 MiB", or validation stops. The core is 5.9 MB.
- "Any other binary file, such as … a compiled executable, is held", and so is any file over 256 KiB that
  is not an image or a font.
- "Commit readable source instead of compiled, packed, or minified code."
- No manifest field picks a command by operating system or architecture, so one command must work
  everywhere. A script that picks the binary is itself held ("not through a shell or a package-manager
  script").
- A `bin/` folder is on the Bash tool's `PATH`, but "claude.ai and Cowork don't install a plugin that has
  this directory".

No rule on these pages names a language, and none mentions Rust.

**What changes anyway.**

- **Releases.** One `uv build` becomes a build per platform: macOS arm64 and x86-64, Linux x86-64 and
  aarch64 (glibc and musl), Windows x64. The prototype's wheel is tagged `manylinux_2_34`, because it was
  built on this machine; a release needs an older baseline.
- **Trust.** Today a user can read every line `uvx` installs, and the Safety page links each to its source.
  A binary cannot be read. The page would have to rest on reproducible builds or build attestations.

## 4. What a rewrite costs

- 6,291 lines of `src/` outside the evals, and 249 test functions written against Python objects.
- The evals (3,920 lines) import `Memory` in-process. They would need a Python binding to the Rust core,
  or go through HTTP.
- The same text must come out. The prototype matched on English text. Python's `\w` and Rust's
  `is_alphanumeric` differ on some combining marks, and capture's redaction patterns, the splitter and the
  tokenizer each need the same care. A mismatch in a prompt changes its sha256 and misses the cache.
- Research speed. The arms, rerankers and budgets in this repository were all tried in Python in hours.

## 5. Recommendation

Don't rewrite. In Python, in this order:

1. **Trim the hook's imports.** A socket in place of `urllib`, and no `dataclasses`, `logging` or
   `argparse` on the hook path: 160 ms → about 76 ms per prompt, measured above as a lower bound.
2. **Save the index** (engines note, §6): start-up 6.2 s → an estimated 0.9 s.

After both, Rust would add about 30 ms per prompt, 16-bit vector search and a smaller download. That does
not pay for §4.

What would change this:

- **A Cogi without `uv` or Python**: one binary from Homebrew or WinGet, for Codex and other clients. The
  hook would then cost 9 ms, not 46. The plugin directory would still need the PyPI route.
- **The 100M-token stretch**, if it is built around a native index, or llama.cpp linked into the service.
- **A native hook alone** (0.5 MB, shipped in platform wheels, with the service left in Python) saves 30 ms
  over the trimmed Python hook and still costs the per-platform builds. Not worth it by itself.

## 6. Reproduce

```bash
# the memory, the queries and the Python numbers (see search_engines_20261111.md)
python scripts/engines/bench.py fill  --data longmemeval_s_cleaned.json --root runs/m10 --tokens 10M
python scripts/engines/bench.py speed --root runs/m10 --engine baseline
# query texts and vectors for the Rust core: bench.query_set(root, 1000) as JSON, and
# bench.RandomEmbedder().embed([bench.query_prompt(t) for t in texts]) written with .astype("<f4").tofile(...)
cd scripts/rust_probe && cargo build --release
target/release/cogi bench ../../runs/m10 qtexts.json qvecs.f32 rust-core.json
# the hook: a service on the same memory, then 50 runs of each form
COGITO_MEM_HOME=home cogito-mem serve --embedder none --port 7399 &
python timeit.py 50 hook.json uvx cogito-mem==0.3.0 recall claude-code
python timeit.py 50 hook.json target/release/cogi-hook
uvx maturin build --release --bindings bin --strip -o dist    # the wheel
```

Limits: one Linux VM, warm caches, keyword search in the hook runs (no embedding model in the service).
macOS and Windows were not built.
