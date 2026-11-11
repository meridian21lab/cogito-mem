"""Compare cogito-mem's own index with embedded search engines on the same memory.

cogito-mem keeps its append-only log in SQLite and rebuilds the BM25 index, the filter columns and the
vector matrix in RAM every time a namespace is opened (src/cogito_mem/store.py). This script measures that
against engines that keep text, filters and vectors on disk, side by side:

- ``baseline``: cogito-mem as it ships (``Namespace.search``);
- ``sqlite``: SQLite FTS5 (BM25) and sqlite-vec (exact KNN with metadata filters), next to the log;
- ``zvec``: zvec, an in-process vector database (FTS, fp16 flat vectors, inverted filter indexes);
- ``lance``: LanceDB (its native FTS and flat vector search over Lance files).

Every engine indexes exactly the text cogito-mem's BM25 indexes (author, title and the piece's text, cut
into cogito-mem's own terms and joined by spaces) and is queried with cogito-mem's query terms, so a
difference in ranking comes from the engine, not from tokenization. Vectors are random (a hash of the
prompt seeds them) because every engine here searches them exactly; ``parity`` checks that.

    python scripts/engines/bench.py fill    --data longmemeval_s_cleaned.json --root R --tokens 10M
    python scripts/engines/bench.py build   --root R --engine sqlite
    python scripts/engines/bench.py speed   --root R --engine sqlite
    python scripts/engines/bench.py parity  --root R
    python scripts/engines/bench.py quality --data longmemeval_s_cleaned.json --out R/quality.json
    python scripts/engines/bench.py churn   --root R --engine zvec [--with-vectors]
    python scripts/engines/bench.py snapshot --root R
    python scripts/engines/bench.py scale   --root R/scale --items 1000000

``scripts/engines/run_all.sh`` runs fill, build, speed, parity and scale in order; the write-up is
``docs/notes/search_engines_20261111.md``.

Needs ``pip install sqlite-vec zvec lancedb psutil``; none of them is a cogito-mem dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import random
import resource
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):  # as `cogito-mem serve` does
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

from cogito_mem import timeutil  # noqa: E402
from cogito_mem.api import DEFAULT_TOP_K, FilterIn  # noqa: E402
from cogito_mem.embedding import DIM, PROFILES, finish, query_prompt  # noqa: E402
from cogito_mem.evals.longmemeval import NO_BUDGET, load, load_question, parse_date  # noqa: E402
from cogito_mem.evals.longmemeval_recall import KS, NDCG_K, distinct, score  # noqa: E402
from cogito_mem.evals.speed import _lme_sessions, fill  # noqa: E402
from cogito_mem.memory import Config, Memory  # noqa: E402
from cogito_mem.terms import query_terms, terms  # noqa: E402
from cogito_mem.tokenizer import ApproxTokenizer  # noqa: E402

NS = "bench"
NEVER = int(np.iinfo(np.int64).max)
POOL = 100  # Config.candidates: each list is read to max(100, 3 * top_k)
ENGINES = ("baseline", "sqlite", "zvec", "lance")
EMPTY = np.empty(0, np.int64)


class RandomEmbedder:
    """A stand-in for EmbeddingGemma: a unit vector seeded by the prompt's hash, so every run agrees."""

    name = "random-sha256-v1"
    profile = PROFILES["embeddinggemma"]

    def __init__(self) -> None:
        self.tokenizer = ApproxTokenizer()

    def embed(self, prompts) -> np.ndarray:
        out = np.empty((len(prompts), DIM), np.float32)
        for i, p in enumerate(prompts):
            seed = int.from_bytes(hashlib.sha256(p.encode("utf-8")).digest()[:8], "little")
            out[i] = np.random.default_rng(seed).standard_normal(DIM)
        return finish(out)


@dataclass(frozen=True)
class Flt:
    as_of: int
    thread: int | None = None  # the namespace's thread code
    valid_before: int | None = None

    def sql(self, prefix: str = "") -> tuple[str, list]:
        where = [f"{prefix}created <= ?", f"{prefix}retracted > ?"]
        args: list = [self.as_of, self.as_of]
        if self.thread is not None:
            where.append(f"{prefix}thread = ?")
            args.append(self.thread)
        if self.valid_before is not None:
            where.append(f"{prefix}valid < ?")
            args.append(self.valid_before)
        return " AND ".join(where), args

    def text(self) -> str:
        """The filter with its values written in, for engines that take a filter string."""
        where, args = self.sql()
        for a in args:
            where = where.replace("?", str(int(a)), 1)
        return where


# --------------------------------------------------------------------------- rows


def export(ns, rows: list[int] | None = None) -> dict:
    """The namespace's rows as the engines index them: the BM25 text, the filter columns, the vectors."""
    with ns.lock:
        n = len(ns.row_ids)
        idx = np.arange(n) if rows is None else np.asarray(rows, np.int64)
        body = []
        for row in idx.tolist():
            msg = ns.messages[int(ns._row_msg.data[row])]
            text = ns.row_text(row)
            text = f"{msg.title}\n{text}" if msg.title else text  # as Namespace._index gives it to BM25
            if ns.index_author:
                text = f"{msg.author}: {text}"
            body.append(" ".join(terms(text)))
        return {
            "rowid": idx,
            "body": body,
            "created": ns._row_created.data[idx].copy(),
            "valid": ns._row_valid.data[idx].copy(),
            "thread": ns._row_thread.data[idx].copy(),
            "author": ns._row_author.data[idx].copy(),
            "kind": ns._row_kind.data[idx].copy(),
            "retracted": ns._row_retracted.data[idx].copy(),
            "has_vec": ns._has_vec.data[idx].copy(),
            "vec": ns._vectors[idx].astype(np.float16),
        }


def chunks(n: int, size: int):
    for i in range(0, n, size):
        yield slice(i, min(i + size, n))


def take(rows: dict, sl: slice) -> dict:
    return {k: (v[sl] if not isinstance(v, list) else v[sl]) for k, v in rows.items()}


# --------------------------------------------------------------------------- engines


class Baseline:
    """cogito-mem as it ships: the log in SQLite, everything else rebuilt in RAM."""

    name = "baseline"

    def __init__(self, root: Path | None = None, mem: Memory | None = None, ns=None, cache: Path | None = None):
        kw = {"cache_path": cache} if cache is not None else {}
        self.mem = mem or Memory(root, embedder=RandomEmbedder(), config=Config(), query_cache=0, **kw)
        self.ns = ns or self.mem.namespace(NS)
        self.names = {c: t for t, c in self.ns.thread_codes.items()}

    def ready(self) -> None:
        self.mem.flush()  # every vector back from the embedding cache

    def _filter(self, flt: Flt) -> FilterIn:
        thread = self.names.get(flt.thread) if flt.thread is not None else None
        return FilterIn(thread_id=thread, valid_before=flt.valid_before)

    def keyword(self, text: str, flt: Flt, pool: int) -> np.ndarray:
        ns = self.ns
        with ns.lock:
            ns._refresh_locked()
            n = len(ns.row_ids)
            mask = ns._mask(self._filter(flt), flt.as_of, n)
            rows, scores = ns.bm25.scores(text, n)
            keep = mask[rows]
            return ns._top(rows[keep], scores[keep], pool)

    def vector(self, qvec: np.ndarray, flt: Flt, pool: int) -> np.ndarray:
        ns = self.ns
        with ns.lock:
            ns._refresh_locked()
            n = len(ns.row_ids)
            idx = np.flatnonzero(ns._mask(self._filter(flt), flt.as_of, n) & ns._has_vec.view(n))
            if not len(idx):
                return EMPTY
            sims = ns._vectors[idx] @ qvec if len(idx) * 4 < n else (ns._vectors[:n] @ qvec)[idx]
            return ns._top(idx, sims, pool)

    def hybrid(self, text: str, qvec: np.ndarray, flt: Flt, pool: int) -> np.ndarray:
        cands = self.ns.search(text, qvec, self._filter(flt), flt.as_of, pool, True)
        return np.fromiter((c.row for c in cands), np.int64, len(cands))

    def append_message(self, item: dict) -> list[int]:
        resp = self.mem.handle({"op": "append", "namespace": NS, "items": [item]})
        return self.ns.messages[self.ns.msg_by_id[resp["items"][0]["id"]]].rows

    def count(self) -> int:
        return len(self.ns.row_ids)

    def close(self) -> None:
        self.mem.close()


class Fused:
    """What every other engine shares: the two lists, fused as Namespace.search fuses them."""

    def hybrid(self, text: str, qvec: np.ndarray, flt: Flt, pool: int, rrf_k: int = 60) -> np.ndarray:
        fused: dict[int, float] = {}
        first: dict[int, int] = {}
        for lst in (self.vector(qvec, flt, pool), self.keyword(text, flt, pool)):
            for rank, row in enumerate(lst.tolist(), start=1):
                fused[row] = fused.get(row, 0.0) + 1.0 / (rrf_k + rank)
                first[row] = min(first.get(row, rank), rank)
        order = sorted(fused, key=lambda r: (-fused[r], first[r], -r))[:pool]
        return np.asarray(order, np.int64)


class SqliteEngine(Fused):
    """SQLite FTS5 for BM25 and sqlite-vec for exact KNN, in one SQLite file with the filter columns."""

    name = "sqlite"
    SCHEMA = f"""
    CREATE TABLE IF NOT EXISTS items (
        rowid INTEGER PRIMARY KEY, created INTEGER NOT NULL, valid INTEGER NOT NULL, thread INTEGER NOT NULL,
        author INTEGER NOT NULL, kind INTEGER NOT NULL, retracted INTEGER NOT NULL);
    CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(body, content='', tokenize="unicode61 remove_diacritics 0");
    CREATE VIRTUAL TABLE IF NOT EXISTS vec USING vec0(
        embedding float[{DIM}] distance_metric=cosine,
        created integer, valid integer, thread integer, author integer, kind integer, retracted integer);
    """

    def __init__(self, path: Path, create: bool = False):
        import sqlite_vec

        path.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(str(path / "index.sqlite3"), isolation_level=None, check_same_thread=False)
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA mmap_size=4294967296")
        self.db.execute("PRAGMA cache_size=-131072")  # 128 MB
        self.db.executescript(self.SCHEMA)

    def ready(self) -> None:
        pass

    def build(self, rows: dict) -> None:
        self.db.execute("BEGIN")
        self._insert(rows)
        self._vectors(rows, rows["has_vec"])
        self.db.execute("COMMIT")
        self.db.execute("INSERT INTO fts(fts) VALUES ('optimize')")

    def _insert(self, rows: dict) -> None:
        cols = [rows[k].tolist() for k in ("rowid", "created", "valid", "thread", "author", "kind", "retracted")]
        self.db.executemany("INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?)", zip(*cols))
        self.db.executemany("INSERT INTO fts (rowid, body) VALUES (?, ?)", zip(cols[0], rows["body"]))

    def _vectors(self, rows: dict, which: np.ndarray) -> None:
        idx = np.flatnonzero(which)
        if not len(idx):
            return
        vecs = rows["vec"][idx].astype(np.float32)
        meta = [rows[k][idx].tolist() for k in ("rowid", "created", "valid", "thread", "author", "kind", "retracted")]
        self.db.executemany(
            "INSERT INTO vec (rowid, embedding, created, valid, thread, author, kind, retracted) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ((m[0], v.tobytes(), *m[1:]) for m, v in zip(zip(*meta), vecs)),
        )

    def count(self) -> int:
        return self.db.execute("SELECT (SELECT count(*) FROM items) + 0 * (SELECT count(*) FROM vec)").fetchone()[0]

    def append(self, rows: dict) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        self._insert(rows)
        self.db.execute("COMMIT")

    def set_vectors(self, rows: dict) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        self._vectors(rows, np.ones(len(rows["rowid"]), bool))
        self.db.execute("COMMIT")

    def keyword(self, text: str, flt: Flt, pool: int) -> np.ndarray:
        qt = sorted(query_terms(text))
        if not qt:
            return EMPTY
        where, args = flt.sql("i.")
        sql = (
            "SELECT f.rowid FROM fts f JOIN items i ON i.rowid = f.rowid "
            f"WHERE fts MATCH ? AND {where} ORDER BY bm25(fts), f.rowid LIMIT ?"
        )
        match = " OR ".join(f'"{t}"' for t in qt)
        return np.fromiter((r for (r,) in self.db.execute(sql, (match, *args, pool))), np.int64)

    def vector(self, qvec: np.ndarray, flt: Flt, pool: int) -> np.ndarray:
        where, args = flt.sql()
        sql = f"SELECT rowid FROM vec WHERE embedding MATCH ? AND k = ? AND {where} ORDER BY distance"
        blob = np.asarray(qvec, np.float32).tobytes()
        return np.fromiter((r for (r,) in self.db.execute(sql, (blob, pool, *args))), np.int64)

    def close(self) -> None:
        self.db.close()


class ZvecEngine(Fused):
    """zvec: one collection holding the BM25 text, the filter columns and fp16 vectors (flat, exact)."""

    name = "zvec"

    def __init__(self, path: Path, create: bool = False):
        import zvec
        from zvec import (CollectionSchema, DataType, FieldSchema, FlatIndexParam, FtsIndexParam, InvertIndexParam,
                          MetricType, VectorSchema)  # fmt: skip

        self.z = zvec
        where = str(path / "zvec")
        if create:
            path.mkdir(parents=True, exist_ok=True)
            ranged = InvertIndexParam(enable_range_optimization=True)
            schema = CollectionSchema(
                name="items",
                fields=[
                    FieldSchema("body", DataType.STRING, index_param=FtsIndexParam(tokenizer_name="whitespace", filters=[])),
                    FieldSchema("created", DataType.INT64, index_param=ranged),
                    FieldSchema("valid", DataType.INT64, index_param=ranged),
                    FieldSchema("retracted", DataType.INT64, index_param=ranged),
                    FieldSchema("thread", DataType.INT32, index_param=InvertIndexParam()),
                    FieldSchema("author", DataType.INT32, index_param=InvertIndexParam()),
                    FieldSchema("kind", DataType.INT32, index_param=InvertIndexParam()),
                    FieldSchema("has_vec", DataType.BOOL, index_param=InvertIndexParam()),
                ],
                vectors=[VectorSchema("vec", DataType.VECTOR_FP16, dimension=DIM,
                                      index_param=FlatIndexParam(metric_type=MetricType.IP))],
            )  # fmt: skip
            self.col = zvec.create_and_open(path=where, schema=schema)
        else:
            self.col = zvec.open(path=where)

    def ready(self) -> None:
        pass

    def _docs(self, rows: dict, with_vectors: bool) -> list:
        Doc = self.z.Doc
        out = []
        zero = np.zeros(DIM, np.float16)
        for i, rowid in enumerate(rows["rowid"].tolist()):
            has = bool(rows["has_vec"][i]) and with_vectors
            out.append(Doc(
                id=str(rowid),
                fields={"body": rows["body"][i], "created": int(rows["created"][i]), "valid": int(rows["valid"][i]),
                        "retracted": int(rows["retracted"][i]), "thread": int(rows["thread"][i]),
                        "author": int(rows["author"][i]), "kind": int(rows["kind"][i]), "has_vec": has},
                vectors={"vec": rows["vec"][i] if has else zero},
            ))  # fmt: skip
        return out

    def build(self, rows: dict) -> None:
        for sl in chunks(len(rows["rowid"]), 1000):  # zvec takes at most 1,024 docs a write
            self.col.insert(self._docs(take(rows, sl), True))
        self.col.optimize()
        self.col.flush()

    def count(self) -> int:
        return int(self.col.stats.doc_count)

    def append(self, rows: dict) -> None:
        self.col.insert(self._docs(rows, False))  # zvec's WAL keeps it through a crash without flush()

    def build_more(self, rows: dict) -> None:
        self.col.insert(self._docs(rows, True))

    def set_vectors(self, rows: dict) -> None:
        Doc = self.z.Doc
        self.col.update([Doc(id=str(r), fields={"has_vec": True}, vectors={"vec": v})
                         for r, v in zip(rows["rowid"].tolist(), rows["vec"])])  # fmt: skip

    def keyword(self, text: str, flt: Flt, pool: int) -> np.ndarray:
        qt = sorted(query_terms(text))
        if not qt:
            return EMPTY
        z = self.z
        q = z.Query(field_name="body", fts=z.Fts(match_string=" ".join(qt)), param=z.FtsQueryParam(default_operator="OR"))
        # zvec 0.8.1 fails a filtered FTS query asking for no fields while unoptimised rows exist, so ask for one.
        res = self.col.query(q, topk=pool, filter=flt.text(), output_fields=["created"])
        return np.fromiter((int(d.id) for d in res), np.int64)

    def vector(self, qvec: np.ndarray, flt: Flt, pool: int) -> np.ndarray:
        z = self.z
        res = self.col.query(z.Query(field_name="vec", vector=np.asarray(qvec, np.float32)), topk=pool,
                             filter=flt.text() + " AND has_vec = true", output_fields=["created"])  # fmt: skip
        return np.fromiter((int(d.id) for d in res), np.int64)

    def close(self) -> None:
        self.col.close() if hasattr(self.col, "close") else None


class LanceEngine(Fused):
    """LanceDB: one table with the BM25 text, the filter columns and fp16 vectors; native FTS, no ANN index."""

    name = "lance"

    def __init__(self, path: Path, create: bool = False):
        import lancedb
        import pyarrow as pa

        self.pa = pa
        path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(path / "lance"))
        self.schema = pa.schema([
            ("rowid", pa.int64()), ("body", pa.string()), ("created", pa.int64()), ("valid", pa.int64()),
            ("retracted", pa.int64()), ("thread", pa.int32()), ("author", pa.int32()), ("kind", pa.int8()),
            ("has_vec", pa.bool_()), ("vec", pa.list_(pa.float16(), DIM)),
        ])  # fmt: skip
        self.table = None if create else self.db.open_table("items")

    def ready(self) -> None:
        pass

    def _arrow(self, rows: dict, with_vectors: bool):
        pa = self.pa
        has = rows["has_vec"] if with_vectors else np.zeros(len(rows["rowid"]), bool)
        vec = np.where(has[:, None], rows["vec"], np.float16(0)).astype(np.float16)
        return pa.table({
            "rowid": rows["rowid"].astype(np.int64), "body": rows["body"], "created": rows["created"].astype(np.int64),
            "valid": rows["valid"].astype(np.int64), "retracted": rows["retracted"].astype(np.int64),
            "thread": rows["thread"].astype(np.int32), "author": rows["author"].astype(np.int32),
            "kind": rows["kind"].astype(np.int8), "has_vec": has,
            "vec": pa.FixedSizeListArray.from_arrays(pa.array(vec.ravel()), DIM),
        }, schema=self.schema)  # fmt: skip

    def build(self, rows: dict) -> None:
        self.table = self.db.create_table("items", self._arrow(rows, True), mode="overwrite")
        self.table.create_fts_index("body", use_tantivy=False, base_tokenizer="whitespace", lower_case=False, stem=False,
                                    remove_stop_words=False, ascii_folding=False, with_position=False, replace=True)  # fmt: skip
        for col in ("created", "valid", "thread"):
            self.table.create_scalar_index(col, replace=True)

    def count(self) -> int:
        return int(self.table.count_rows())

    def append(self, rows: dict) -> None:
        self.table.add(self._arrow(rows, False))

    def set_vectors(self, rows: dict) -> None:
        for rowid, vec in zip(rows["rowid"].tolist(), rows["vec"]):
            self.table.update(where=f"rowid = {rowid}", values={"has_vec": True, "vec": vec.astype(np.float32).tolist()})

    def optimize(self) -> None:
        self.table.optimize()

    def keyword(self, text: str, flt: Flt, pool: int) -> np.ndarray:
        qt = sorted(query_terms(text))
        if not qt:
            return EMPTY
        q = self.table.search(" ".join(qt), query_type="fts", fts_columns="body")
        res = q.where(flt.text(), prefilter=True).limit(pool).select(["rowid", "_score"]).to_arrow()
        return res["rowid"].to_numpy().astype(np.int64)

    def vector(self, qvec: np.ndarray, flt: Flt, pool: int) -> np.ndarray:
        q = self.table.search(np.asarray(qvec, np.float32), vector_column_name="vec").distance_type("dot")
        res = q.where(flt.text() + " AND has_vec", prefilter=True).limit(pool).select(["rowid", "_distance"]).to_arrow()
        return res["rowid"].to_numpy().astype(np.int64)

    def close(self) -> None:
        pass


CLASSES = {"sqlite": SqliteEngine, "zvec": ZvecEngine, "lance": LanceEngine}


def open_engine(name: str, root: Path, cache: Path | None = None):
    return Baseline(root, cache=cache) if name == "baseline" else CLASSES[name](root / "engines" / name)


def private_copy(name: str, root: Path) -> Path:
    """A copy of what this engine opens, so the append test leaves the original as it was."""
    work = Path(tempfile.mkdtemp(prefix=f"speed-{name}-", dir=root))
    if name == "baseline":
        shutil.copytree(root / "memory", work / "memory")
    else:
        shutil.copytree(root / "engines" / name, work / "engines" / name)
    return work


# --------------------------------------------------------------------------- measuring


def stats(ms: list[float]) -> dict:
    if not ms:
        return {}
    xs = sorted(ms)
    p95 = xs[min(len(xs) - 1, int(round(0.95 * len(xs))) - 1)]
    return {"n": len(xs), "median_ms": round(statistics.median(xs), 3), "p95_ms": round(p95, 3),
            "max_ms": round(xs[-1], 3), "mean_ms": round(statistics.fmean(xs), 3)}  # fmt: skip


def memory_now() -> dict:
    import psutil

    info = psutil.Process().memory_full_info()
    return {"rss_mb": round(info.rss / 2**20, 1), "uss_mb": round(info.uss / 2**20, 1),
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}  # fmt: skip


def du(path: Path) -> float:
    if not path.exists():
        return 0.0
    if path.is_file():
        return round(path.stat().st_size / 2**20, 1)
    return round(sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 2**20, 1)


def baseline_disk(root: Path) -> dict:
    folder = root / "memory" / NS
    return {"log_mb": du(folder), "embedding_cache_mb": du(root / "cache")}


# --------------------------------------------------------------------------- commands


def cmd_fill(args) -> int:
    root = Path(args.root)
    save_queries(Path(args.data), root)
    mem = Memory(root, embedder=RandomEmbedder(), config=Config(), query_cache=0, embed_batch=512)
    t0 = time.perf_counter()
    used, total = fill(mem, _lme_sessions(load(Path(args.data))), parse_count(args.tokens))
    fill_s = time.perf_counter() - t0
    ns = mem.namespace(NS)
    mem.flush()
    info = {"tokens": total, "items": len(ns.row_ids), "messages": len(ns.messages), "sessions": len(used),
            "fill_s": round(fill_s, 1), "all_s": round(time.perf_counter() - t0, 1)}  # fmt: skip
    mem.close()
    (root / "fill.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    return 0


def cmd_build(args) -> int:
    root = Path(args.root)
    base = Baseline(root)
    base.ready()
    rows = export(base.ns)
    base.close()
    target = root / "engines" / args.engine
    shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    np.save(target.parent / "threads.npy", rows["thread"])
    t0 = time.perf_counter()
    eng = CLASSES[args.engine](target, create=True)
    eng.build(rows)
    eng.close()
    info = {"engine": args.engine, "items": len(rows["rowid"]), "build_s": round(time.perf_counter() - t0, 1),
            "disk_mb": du(target)}  # fmt: skip
    (root / f"build-{args.engine}.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    return 0


def save_queries(data: Path, root: Path) -> None:
    """The questions alone, so a speed run does not hold the whole dataset in memory while it is measured."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "queries.json").write_text(json.dumps([q["question"] for q in load(data)]))


def query_set(root: Path, n: int, seed: int = 0) -> list[str]:
    qs = json.loads((root / "queries.json").read_text())
    random.Random(seed).shuffle(qs)
    return [qs[i % len(qs)] + (f" ({i})" if i >= len(qs) else "") for i in range(n)]


def appended_texts(root: Path, n: int, seed: int = 1) -> list[str]:
    """Messages from the memory itself, one piece each, marked so the test can find each again."""
    db = sqlite3.connect(str(root / "memory" / NS / "log.sqlite3"))
    texts = [t for (t,) in db.execute("SELECT text FROM log WHERE pieces NOT LIKE '%],[%' AND length(text) > 200 LIMIT 5000")]
    db.close()
    rng = random.Random(seed)
    return [rng.choice(texts) + f" zqmarker{i}x" for i in range(n)]


def new_rows(start_row: int, texts: list[str], now: int, thread: int, embedder) -> dict:
    """What a live append of these one-piece messages adds to an engine (author ``user``, a new thread)."""
    body = [" ".join(terms(f"user: {t}")) for t in texts]
    k = len(texts)
    created = np.arange(now, now + k, dtype=np.int64)
    return {"rowid": np.arange(start_row, start_row + k, dtype=np.int64), "body": body, "created": created,
            "valid": created.copy(), "thread": np.full(k, thread, np.int32), "author": np.zeros(k, np.int32),
            "kind": np.zeros(k, np.int8), "retracted": np.full(k, NEVER, np.int64), "has_vec": np.ones(k, bool),
            "vec": embedder.embed([f"title: none | text: {t}" for t in texts]).astype(np.float16)}  # fmt: skip


def cmd_speed(args) -> int:
    root = Path(args.root)
    name = args.engine
    embedder = RandomEmbedder()
    texts = query_set(root, args.queries)
    qvecs = embedder.embed([query_prompt(t) for t in texts])  # embedding the query is the same for every engine
    rows_meta = sqlite3.connect(str(root / "memory" / NS / "log.sqlite3"))
    max_created = rows_meta.execute("SELECT max(created_at) FROM log").fetchone()[0]
    valids = [v for (v,) in rows_meta.execute("SELECT valid_at FROM log ORDER BY valid_at")]
    rows_meta.close()
    window = valids[int(len(valids) * 0.3)]
    out: dict = {"engine": name, "queries": len(texts), "memory_before_open": memory_now()}

    work = private_copy(name, root)
    t0 = time.perf_counter()
    __import__({"baseline": "cogito_mem.store", "sqlite": "sqlite_vec", "zvec": "zvec", "lance": "lancedb"}[name])
    out["import_s"] = round(time.perf_counter() - t0, 3)  # the library itself, before it opens anything
    t0 = time.perf_counter()
    eng = open_engine(name, work, cache=root / "cache" / "embeddings.sqlite3")
    out["open_s"] = round(time.perf_counter() - t0, 3)
    flt_all = Flt(as_of=max_created + 1)
    first_kw = eng.keyword(texts[0], flt_all, POOL)
    out["first_keyword_query_s"] = round(time.perf_counter() - t0, 3)
    eng.ready()
    first = eng.hybrid(texts[0], qvecs[0], flt_all, POOL)
    out["ready_s"] = round(time.perf_counter() - t0, 3)  # keyword and vector search both answer
    out["first_query_found"] = [int(len(first_kw)), int(len(first))]
    out["memory_after_open"] = memory_now()

    threads = np.load(root / "engines" / "threads.npy")  # each row's thread code, saved by ``build``
    n_items = len(threads)
    out["items"] = eng.count()
    if out["items"] != n_items:
        raise SystemExit(f"{name} holds {out['items']} items, the memory {n_items}: build it again")
    rng = np.random.default_rng(0)
    pick_threads = threads[rng.integers(0, n_items, len(texts))]
    variants = {
        "all": lambda i: flt_all,
        "thread": lambda i: Flt(as_of=max_created + 1, thread=int(pick_threads[i])),
        "before": lambda i: Flt(as_of=max_created + 1, valid_before=window),
    }
    keep = args.keep
    lists: dict = {}
    timing: dict = {}
    for vname, flt_of in variants.items():
        m = len(texts) if vname == "all" else len(texts) // 2
        for _ in range(10):  # warm-up
            eng.hybrid(texts[0] + " warm", qvecs[0], flt_of(0), POOL)
        for lane in ("keyword", "vector", "hybrid"):
            ms, saved = [], []
            for i in range(m):
                t1 = time.perf_counter()
                if lane == "keyword":
                    res = eng.keyword(texts[i], flt_of(i), POOL)
                elif lane == "vector":
                    res = eng.vector(qvecs[i], flt_of(i), POOL)
                else:
                    res = eng.hybrid(texts[i], qvecs[i], flt_of(i), POOL)
                ms.append((time.perf_counter() - t1) * 1000)
                if i < keep:
                    saved.append(res.tolist())
            timing[f"{vname}/{lane}"] = stats(ms)
            lists[f"{vname}/{lane}"] = saved
            print(f"{name} {vname}/{lane}: {timing[f'{vname}/{lane}']}", file=sys.stderr)
    out["query"] = timing
    out["memory_after_queries"] = memory_now()

    # Appends, one message at a time as capture sends them: the call (searchable by keyword when it returns),
    # then the vector (in cogito-mem the background worker stores it), then whether the next query sees it.
    adds = appended_texts(root, args.appends)
    now = max(timeutil.now_ms(), max_created + 1)
    append_ms, vector_ms, found = [], [], 0
    if name == "baseline":
        for i, text in enumerate(adds):
            t1 = time.perf_counter()
            rows_added = eng.append_message({"author": "user", "thread_id": "bench-appends", "text": text})
            append_ms.append((time.perf_counter() - t1) * 1000)
            found += int(bool(set(rows_added) & set(eng.keyword(f"zqmarker{i}x", Flt(as_of=NEVER - 1), 10).tolist())))
        t1 = time.perf_counter()
        eng.mem.flush()
        vector_ms.append((time.perf_counter() - t1) * 1000)
    else:
        start = n_items
        for i, text in enumerate(adds):
            rows = new_rows(start + i, [text], now + i, int(threads.max()) + 1, embedder)
            t1 = time.perf_counter()
            eng.append(rows)
            append_ms.append((time.perf_counter() - t1) * 1000)
            t1 = time.perf_counter()
            eng.set_vectors(rows)
            vector_ms.append((time.perf_counter() - t1) * 1000)
            found += int(start + i in eng.keyword(f"zqmarker{i}x", Flt(as_of=NEVER - 1), 10).tolist())
    out["append"] = {"n": len(adds), "append_call": stats(append_ms), "store_vector": stats(vector_ms),
                     "found_by_keyword_right_after": found}  # fmt: skip
    after = Flt(as_of=NEVER - 1)
    ms = []
    for i in range(min(200, len(texts))):
        t1 = time.perf_counter()
        eng.hybrid(texts[i], qvecs[i], after, POOL)
        ms.append((time.perf_counter() - t1) * 1000)
    out["query_after_appends"] = {"all/hybrid": stats(ms)}
    if name == "lance":
        t1 = time.perf_counter()
        eng.optimize()
        out["lance_optimize_s"] = round(time.perf_counter() - t1, 2)
        ms = []
        for i in range(min(200, len(texts))):
            t1 = time.perf_counter()
            eng.hybrid(texts[i], qvecs[i], after, POOL)
            ms.append((time.perf_counter() - t1) * 1000)
        out["query_after_optimize"] = {"all/hybrid": stats(ms)}
    out["memory_end"] = memory_now()
    out["disk_mb"] = baseline_disk(root) if name == "baseline" else du(root / "engines" / name)
    out["disk_mb_after_appends"] = du(work / "memory") if name == "baseline" else du(work / "engines" / name)
    eng.close()
    shutil.rmtree(work, ignore_errors=True)
    (root / f"speed-{name}.json").write_text(json.dumps(out, indent=2))
    (root / f"lists-{name}.json").write_text(json.dumps(lists))
    print(json.dumps({k: v for k, v in out.items()}, indent=2))
    return 0


def overlap(got: list, ref: list, k: int) -> float:
    """The share of the reference's first k found in the engine's first k (both empty: 1)."""
    if not ref[:k]:
        return 1.0 if not got[:k] else 0.0
    return len(set(got[:k]) & set(ref[:k])) / len(ref[:k])


def cmd_parity(args) -> int:
    root = Path(args.root)
    base = json.loads((root / "lists-baseline.json").read_text())
    report: dict = {}
    for name in ENGINES[1:]:
        path = root / f"lists-{name}.json"
        if not path.exists():
            continue
        other = json.loads(path.read_text())
        report[name] = {}
        for key, ref in base.items():
            got = other.get(key, [])
            pairs = list(zip(ref, got))
            report[name][key] = {
                "queries": len(pairs),
                "overlap@10": round(statistics.fmean(overlap(g, r, 10) for r, g in pairs), 4) if pairs else None,
                "overlap@100": round(statistics.fmean(overlap(g, r, 100) for r, g in pairs), 4) if pairs else None,
                "same_top10_order": round(statistics.fmean(r[:10] == g[:10] for r, g in pairs), 4) if pairs else None,
            }
    (root / "parity.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


# --------------------------------------------------------------------------- quality (LongMemEval-S, keyword lane)


def _one_question(job) -> dict:
    q, engines, workdir = job
    mem = Memory(None, embedder=None, config=Config(search="keyword"), query_cache=0)
    present = {str(s) for s in q["haystack_session_ids"]}
    want_sessions = {str(s) for s in q.get("answer_session_ids") or []} & present
    evidence, _ = load_question(mem, q, evidence_sessions=want_sessions)
    want_turns = set(evidence)
    ns = mem.namespace("q")
    as_of_q = parse_date(q["question_date"]) + 59_999
    out = {"question_id": q["question_id"], "question_type": q.get("question_type"), "abstention": "_abs" in str(q["question_id"])}

    def scored(sessions: list[str], turns: list[str]) -> dict:
        return {"session": score(sessions, want_sessions) if want_sessions else None,
                "turn": score(turns, want_turns) if want_turns else None}  # fmt: skip

    pool = max(Config().candidates, 3 * DEFAULT_TOP_K)
    for mode in ("question", "none"):
        body = {"op": "query", "namespace": "q", "text": q["question"], "top_k": DEFAULT_TOP_K, "max_tokens": NO_BUDGET}
        if mode == "question":
            body["as_of"] = timeutil.format(as_of_q)
        resp = mem.handle(body)
        out[f"baseline/{mode}"] = scored(distinct(it["thread_id"] for it in resp["items"]),
                                         distinct(it["source"]["id"] for it in resp["items"]))  # fmt: skip
    rows = export(ns)
    for name in engines:
        folder = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=workdir))
        try:
            eng = CLASSES[name](folder, create=True)
            eng.build(rows)
            for mode in ("question", "none"):
                flt = Flt(as_of=as_of_q if mode == "question" else NEVER - 1)
                hits = eng.keyword(q["question"], flt, pool)[:DEFAULT_TOP_K].tolist()
                msgs = [ns.messages[int(ns._row_msg.data[r])] for r in hits]
                out[f"{name}/{mode}"] = scored(distinct(m.thread_id for m in msgs), distinct(m.id for m in msgs))
            eng.close()
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    mem.close()
    return out


def summarize(rows: list[dict], key: str, level: str = "session") -> dict:
    scored = [r[key][level] for r in rows if r.get(key) and r[key][level]]
    n = len(scored)
    if not n:
        return {"n": 0}
    out = {"n": n}
    for k in KS:
        out[f"R@{k}"] = round(sum(s[f"recall_any@{k}"] for s in scored) / n, 4)
    out["recall_all@5"] = round(sum(s["recall_all@5"] for s in scored) / n, 4)
    out[f"ndcg@{NDCG_K}"] = round(sum(s[f"ndcg@{NDCG_K}"] for s in scored) / n, 4)
    out["mrr"] = round(sum(1 / s["rank"] for s in scored if s["rank"]) / n, 4)
    return out


def paired(rows: list[dict], a: str, b: str, metric: str = "recall_any@5", level: str = "session", reps: int = 2000) -> dict:
    """b minus a over the questions both scored, with a 95 % bootstrap interval, in points."""
    diffs = [float(r[b][level][metric]) - float(r[a][level][metric]) for r in rows
             if r.get(a) and r.get(b) and r[a][level] and r[b][level]]  # fmt: skip
    if not diffs:
        return {}
    rng = np.random.default_rng(0)
    d = np.asarray(diffs)
    boots = d[rng.integers(0, len(d), (reps, len(d)))].mean(axis=1)
    return {"diff_points": round(100 * d.mean(), 2), "ci95": [round(100 * np.percentile(boots, 2.5), 2), round(100 * np.percentile(boots, 97.5), 2)],
            "better": int((d > 0).sum()), "worse": int((d < 0).sum())}  # fmt: skip


def cmd_quality(args) -> int:
    questions = load(Path(args.data))
    if args.limit:
        questions = questions[: args.limit]
    engines = [e for e in args.engines.split(",") if e in CLASSES]
    workdir = Path(args.work or tempfile.mkdtemp(prefix="engines-quality-"))
    workdir.mkdir(parents=True, exist_ok=True)
    jobs = [(q, engines, str(workdir)) for q in questions]
    rows: list[dict] = []
    t0 = time.perf_counter()
    with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
        for i, row in enumerate(pool.imap_unordered(_one_question, jobs, chunksize=2), 1):
            rows.append(row)
            if i % 25 == 0:
                print(f"{i}/{len(jobs)} questions, {time.perf_counter() - t0:.0f} s", file=sys.stderr)
    rows.sort(key=lambda r: str(r["question_id"]))
    report: dict = {"questions": len(rows), "engines": ["baseline", *engines], "seconds": round(time.perf_counter() - t0, 1)}
    for mode in ("question", "none"):
        for subset, keep in (("all", lambda r: True), ("answerable", lambda r: not r["abstention"])):
            sub = [r for r in rows if keep(r)]
            for name in ["baseline", *engines]:
                key = f"{name}/{mode}"
                report[f"{subset}/{mode}/{name}"] = {"session": summarize(sub, key), "turn": summarize(sub, key, "turn")}
                if name != "baseline":
                    report[f"{subset}/{mode}/{name}"]["vs_baseline_R@5"] = paired(sub, f"baseline/{mode}", key)
                    report[f"{subset}/{mode}/{name}"]["vs_baseline_ndcg@10"] = paired(sub, f"baseline/{mode}", key, f"ndcg@{NDCG_K}")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"report": report, "rows": rows}, indent=1))
    print(json.dumps(report, indent=2))
    return 0


# --------------------------------------------------------------------------- churn (live appends over time)


def cmd_churn(args) -> int:
    """How an engine's queries slow down as live appends pile up, and what its compaction costs.

    Capture appends a few items per turn, each followed by its vector, so a day of work adds hundreds of small
    writes. Each step appends ``--step`` one-piece messages (and their vectors), then times 200 hybrid queries.
    """
    root = Path(args.root)
    name = args.engine
    embedder = RandomEmbedder()
    texts = query_set(root, 200)
    qvecs = embedder.embed([query_prompt(t) for t in texts])
    threads = np.load(root / "engines" / "threads.npy")
    work = private_copy(name, root)
    eng = open_engine(name, work, cache=root / "cache" / "embeddings.sqlite3")
    eng.ready()
    flt = Flt(as_of=NEVER - 1)

    def timed() -> dict:
        ms = []
        for t, qv in zip(texts, qvecs):
            t1 = time.perf_counter()
            eng.hybrid(t, qv, flt, POOL)
            ms.append((time.perf_counter() - t1) * 1000)
        return stats(ms)

    steps = [{"appended": 0, "hybrid": timed()}]
    adds = appended_texts(root, args.step * args.steps)
    start, now = len(threads), timeutil.now_ms()
    for s in range(args.steps):
        for i in range(s * args.step, (s + 1) * args.step):
            if name == "baseline":
                eng.append_message({"author": "user", "thread_id": "bench-appends", "text": adds[i]})
                continue
            rows = new_rows(start + i, [adds[i]], now + i, int(threads.max()) + 1, embedder)
            if args.with_vectors:  # the item arrives with its vector: one write, no update
                eng.build_more(rows)
            else:
                eng.append(rows)
                eng.set_vectors(rows)
        eng.ready()
        steps.append({"appended": (s + 1) * args.step, "hybrid": timed()})
        print(name, steps[-1], file=sys.stderr)
    out: dict = {"engine": name, "items": len(threads), "with_vectors": args.with_vectors, "steps": steps}
    compact = getattr(eng, "optimize", None) or getattr(getattr(eng, "col", None), "optimize", None)
    if compact is not None:
        t1 = time.perf_counter()
        compact()
        out["optimize_s"] = round(time.perf_counter() - t1, 2)
        out["after_optimize"] = timed()
    eng.close()
    shutil.rmtree(work, ignore_errors=True)
    (root / f"churn-{name}{'-with-vectors' if args.with_vectors else ''}.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


# --------------------------------------------------------------------------- snapshot (no engine: persist our own index)


def cmd_snapshot(args) -> int:
    """How fast a namespace would open if cogito-mem saved its own BM25 postings and vectors instead of rebuilding.

    Measures the full open (``Namespace``), the same open with BM25 left out (what a snapshot cannot save without
    also changing how messages are held), and loading the postings and the fp16 vectors back from .npy files.
    """
    from cogito_mem.keyword import BM25Index
    from cogito_mem.store import Namespace

    root = Path(args.root)
    work = private_copy("baseline", root)
    folder = work / "memory" / NS
    out: dict = {}
    t0 = time.perf_counter()
    ns = Namespace(NS, folder, index_author=True)
    out["open_s"] = round(time.perf_counter() - t0, 3)
    bm25 = ns.bm25
    real_add = BM25Index.add
    BM25Index.add = lambda self, row, text: None
    t0 = time.perf_counter()
    bare = Namespace(NS, folder, index_author=True)
    out["open_without_bm25_s"] = round(time.perf_counter() - t0, 3)
    BM25Index.add = real_add
    bare.close()

    # Save: every term's postings in one int32 array, with offsets; the lengths; the vectors (fp16, from the cache).
    snap = work / "snapshot"
    snap.mkdir()
    terms_ = list(bm25._postings)
    sizes = np.fromiter((len(bm25._postings[t]) for t in terms_), np.int64, len(terms_))
    offsets = np.concatenate([[0], np.cumsum(sizes)])
    flat = np.empty(int(offsets[-1]), np.int32)
    for t, a, b in zip(terms_, offsets[:-1], offsets[1:]):
        flat[a:b] = np.frombuffer(bm25._postings[t], np.int32)
    t0 = time.perf_counter()
    np.save(snap / "postings.npy", flat)
    np.save(snap / "offsets.npy", offsets)
    np.save(snap / "lengths.npy", np.frombuffer(bm25._lengths, np.float32))
    (snap / "terms.json").write_text(json.dumps(terms_))
    mem = Memory(work, embedder=RandomEmbedder(), config=Config(), query_cache=0, cache_path=root / "cache" / "embeddings.sqlite3")
    full = mem.namespace(NS)
    mem.flush()
    np.save(snap / "vectors.npy", full._vectors[: len(full.row_ids)].astype(np.float16))
    mem.close()
    out["snapshot_write_s"] = round(time.perf_counter() - t0, 3)
    out["snapshot_mb"] = du(snap)

    t0 = time.perf_counter()
    flat2 = np.load(snap / "postings.npy", mmap_mode="r")
    offs = np.load(snap / "offsets.npy")
    names = json.loads((snap / "terms.json").read_text())
    postings = {t: flat2[a:b] for t, a, b in zip(names, offs[:-1].tolist(), offs[1:].tolist())}
    lengths = np.load(snap / "lengths.npy")
    vectors = np.load(snap / "vectors.npy").astype(np.float32)
    out["snapshot_load_s"] = round(time.perf_counter() - t0, 3)
    out["terms"] = len(postings)
    out["rows"] = int(len(lengths))
    out["vectors"] = int(len(vectors))
    out["estimated_open_with_snapshot_s"] = round(out["open_without_bm25_s"] + out["snapshot_load_s"], 3)
    ns.close()
    shutil.rmtree(work, ignore_errors=True)
    (root / "snapshot.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


# --------------------------------------------------------------------------- scale (vectors only)


def cmd_scale(args) -> int:
    """The vector list at the 100M-token stretch size (about 1M items): exact search against zvec's HNSW graph.

    The vectors are points around 2,000 random centres, unit length and rounded to fp16 as cogito-mem keeps
    them, so a graph index has neighbourhoods to find (pure noise would understate it). The filter is
    ``created <= as_of`` with the oldest 70 % visible. numpy's exact answer is the reference for recall.
    """
    import sqlite_vec
    import zvec
    from cogito_mem.store import Namespace

    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    n, nq = args.items, args.queries
    rng = np.random.default_rng(0)
    centres = rng.standard_normal((2000, DIM)).astype(np.float32)
    vec = finish(centres[rng.integers(0, 2000, n)] + 0.6 * rng.standard_normal((n, DIM)).astype(np.float32))
    qs = finish(centres[rng.integers(0, 2000, nq)] + 0.6 * rng.standard_normal((nq, DIM)).astype(np.float32))
    created = np.arange(n, dtype=np.int64)
    as_of = int(n * 0.7)
    out: dict = {"items": n, "queries": nq, "pool": POOL, "visible": as_of + 1}

    def timed(search) -> tuple[dict, list[list[int]]]:
        for i in range(5):
            search(qs[i])
        ms, res = [], []
        for qv in qs:
            t1 = time.perf_counter()
            res.append(search(qv).tolist())
            ms.append((time.perf_counter() - t1) * 1000)
        return stats(ms), res

    def numpy_search(qv):
        idx = np.flatnonzero(created <= as_of)
        sims = vec[idx] @ qv if len(idx) * 4 < n else (vec @ qv)[idx]
        return Namespace._top(idx, sims, POOL)

    out["numpy"], exact = timed(numpy_search)
    out["numpy"]["ram_mb"] = round(vec.nbytes / 2**20, 1)

    def recall(res: list[list[int]], k: int) -> float:
        return round(statistics.fmean(len(set(r[:k]) & set(e[:k])) / k for r, e in zip(res, exact)), 4)

    # sqlite-vec, exact
    db = sqlite3.connect(str(root / "vec.sqlite3"), isolation_level=None)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA mmap_size=4294967296")
    db.execute(f"CREATE VIRTUAL TABLE vec USING vec0(embedding float[{DIM}] distance_metric=cosine, created integer)")
    t1 = time.perf_counter()
    db.execute("BEGIN")
    db.executemany("INSERT INTO vec (rowid, embedding, created) VALUES (?, ?, ?)",
                   ((i, vec[i].tobytes(), i) for i in range(n)))  # fmt: skip
    db.execute("COMMIT")
    build = time.perf_counter() - t1
    sql = "SELECT rowid FROM vec WHERE embedding MATCH ? AND k = ? AND created <= ? ORDER BY distance"
    out["sqlite-vec"], res = timed(lambda qv: np.fromiter((r for (r,) in db.execute(sql, (qv.tobytes(), POOL, as_of))), np.int64))
    out["sqlite-vec"].update({"build_s": round(build, 1), "disk_mb": du(root / "vec.sqlite3"),
                              "recall@10": recall(res, 10), "recall@100": recall(res, 100)})  # fmt: skip
    db.close()

    # zvec, flat (exact) and HNSW
    from zvec import CollectionSchema, DataType, Doc, FieldSchema, FlatIndexParam, HnswIndexParam, HnswQueryParam
    from zvec import InvertIndexParam, MetricType, Query, VectorSchema

    for label, index in (("zvec-flat", FlatIndexParam(metric_type=MetricType.IP)),
                         ("zvec-hnsw", HnswIndexParam(metric_type=MetricType.IP, m=16, ef_construction=200))):  # fmt: skip
        schema = CollectionSchema(name="v", fields=[FieldSchema("created", DataType.INT64, index_param=InvertIndexParam(enable_range_optimization=True))],
                                  vectors=[VectorSchema("vec", DataType.VECTOR_FP16, dimension=DIM, index_param=index)])  # fmt: skip
        t1 = time.perf_counter()
        col = zvec.create_and_open(path=str(root / label), schema=schema)
        v16 = vec.astype(np.float16)
        for sl in chunks(n, 1000):
            col.insert([Doc(id=str(i), fields={"created": i}, vectors={"vec": v16[i]}) for i in range(sl.start, sl.stop)])
        col.optimize()
        col.flush()
        build = time.perf_counter() - t1
        efs = (None,) if label == "zvec-flat" else (100, 200, 400)
        for ef in efs:
            key = label if ef is None else f"{label}-ef{ef}"
            param = None if ef is None else HnswQueryParam(ef=ef)

            def zsearch(qv, param=param, col=col):
                q = Query(field_name="vec", vector=qv, param=param)
                return np.fromiter((int(d.id) for d in col.query(q, topk=POOL, filter=f"created <= {as_of}", output_fields=["created"])), np.int64)

            out[key], res = timed(zsearch)
            out[key].update({"build_s": round(build, 1), "disk_mb": du(root / label),
                             "recall@10": recall(res, 10), "recall@100": recall(res, 100)})  # fmt: skip
            print(key, out[key], file=sys.stderr)
        del col
    (Path(args.out) if args.out else root / "scale.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


# --------------------------------------------------------------------------- main


def parse_count(text: str) -> int:
    text = text.strip().upper()
    mult = {"K": 1_000, "M": 1_000_000}.get(text[-1:], 1)
    return int(float(text[:-1] if mult > 1 else text) * mult)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("fill", help="fill a memory with LongMemEval-S sessions and random vectors")
    s.add_argument("--data", required=True)
    s.add_argument("--root", required=True)
    s.add_argument("--tokens", default="10M")
    s.set_defaults(func=cmd_fill)
    s = sub.add_parser("queries", help="save the dataset's questions for speed runs (fill does it too)")
    s.add_argument("--data", required=True)
    s.add_argument("--root", required=True)
    s.set_defaults(func=lambda a: save_queries(Path(a.data), Path(a.root)))
    s = sub.add_parser("build", help="index the filled memory in one engine")
    s.add_argument("--root", required=True)
    s.add_argument("--engine", required=True, choices=sorted(CLASSES))
    s.set_defaults(func=cmd_build)
    s = sub.add_parser("speed", help="open, query and append, in this process")
    s.add_argument("--root", required=True)
    s.add_argument("--engine", required=True, choices=ENGINES)
    s.add_argument("--queries", type=int, default=1000)
    s.add_argument("--appends", type=int, default=200)
    s.add_argument("--keep", type=int, default=200, help="result lists kept per lane for parity")
    s.set_defaults(func=cmd_speed)
    s = sub.add_parser("parity", help="compare each engine's result lists with the baseline's")
    s.add_argument("--root", required=True)
    s.set_defaults(func=cmd_parity)
    s = sub.add_parser("quality", help="LongMemEval-S session recall of each engine's keyword list")
    s.add_argument("--data", required=True)
    s.add_argument("--engines", default="sqlite,zvec,lance")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--work", help="folder for the per-question indexes")
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_quality)
    s = sub.add_parser("snapshot", help="open time if cogito-mem saved its own postings and vectors (no engine)")
    s.add_argument("--root", required=True)
    s.set_defaults(func=cmd_snapshot)
    s = sub.add_parser("churn", help="queries after rounds of live appends, then after the engine's compaction")
    s.add_argument("--root", required=True)
    s.add_argument("--engine", required=True, choices=ENGINES)
    s.add_argument("--step", type=int, default=500)
    s.add_argument("--steps", type=int, default=4)
    s.add_argument("--with-vectors", action="store_true", help="write each item once, with its vector (engines only)")
    s.set_defaults(func=cmd_churn)
    s = sub.add_parser("scale", help="the vector list at about 1M items: exact search against an HNSW graph")
    s.add_argument("--root", required=True)
    s.add_argument("--items", type=int, default=1_000_000)
    s.add_argument("--queries", type=int, default=500)
    s.add_argument("--out")
    s.set_defaults(func=cmd_scale)
    args = p.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
