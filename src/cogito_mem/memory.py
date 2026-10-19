"""The memory: the two operations over a folder of namespaces.

``Memory.handle(body)`` takes the same dictionary as ``POST /v1/memory`` and the
MCP tools, and returns the response dictionary (or raises ``ApiError``).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

import numpy as np

from . import __version__, timeutil
from .api import DEFAULT_NAMESPACE, AppendIn, QueryIn, parse_append, parse_query
from .embedding import EmbeddingCache, Embedder, HashEmbedder, cache_key, query_prompt
from .errors import ApiError, invalid
from .split import PIECE_TOKENS
from .store import Candidate, Namespace
from .tokenizer import ApproxTokenizer, Tokenizer

log = logging.getLogger("cogito_mem")

FUTURE_SKEW_MS = 5 * 60 * 1000
_DEFAULT = object()


def default_root() -> Path:
    env = os.environ.get("COGITO_MEM_HOME")
    return Path(env).expanduser() if env else Path.home() / ".cogito-mem"


@dataclass
class Config:
    """How the memory searches (the stage-0 arms in requirements §7).

    - ``search``: ``"hybrid"`` (vectors plus BM25, fused by reciprocal rank; arm U2),
      ``"vector"`` (arm U1) or ``"keyword"``.
    - ``doc_context``: ``"previous"`` (default) embeds each item with the message before
      it in the thread (arm U3); ``"own"`` embeds it alone.
    - ``candidates``: how many fused candidates a reranker reorders (arm R).
    - ``doc_author``: write the author's name before the text for embedding and keyword
      search ("Caroline: …"), so "what did Caroline say about…" finds her messages.

    The defaults are the best arm measured so far (LoCoMo, docs/requirements.md §15):
    hybrid search over items embedded with their author and the message before them.
    """

    search: str = "hybrid"
    doc_context: str = "previous"
    doc_author: bool = True
    candidates: int = 30
    rrf_k: int = 60
    piece_tokens: int = PIECE_TOKENS

    def __post_init__(self) -> None:
        if self.search not in ("hybrid", "vector", "keyword"):
            raise ValueError(f"search must be hybrid, vector or keyword, not {self.search!r}")
        if self.doc_context not in ("own", "previous"):
            raise ValueError(f"doc_context must be own or previous, not {self.doc_context!r}")


class Reranker(Protocol):
    name: str

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        """Relevance of each text to the query, between 0 and 1."""
        ...


class Memory:
    def __init__(
        self,
        root: str | Path | None | Any = _DEFAULT,
        *,
        embedder: str | Embedder | None = "auto",
        config: Config | None = None,
        cache_path: str | Path | None | Any = _DEFAULT,
        reranker: Reranker | None = None,
        query_cache: int = 256,
        embed_batch: int = 16,
    ):
        self.root = default_root() if root is _DEFAULT else (Path(root).expanduser() if root is not None else None)
        if self.root is not None:
            (self.root / "memory").mkdir(parents=True, exist_ok=True)
        if cache_path is _DEFAULT:
            cache_path = self.root / "cache" / "embeddings.sqlite3" if self.root is not None else None
        self.cache = EmbeddingCache(cache_path)
        self.config = config or Config()
        self.reranker = reranker
        self._namespaces: dict[str, Namespace] = {}
        self._ns_lock = threading.Lock()
        self._embedder: Embedder | None = None
        self._embedder_state = "none"
        self._tokenizer: Tokenizer = ApproxTokenizer()
        self._query_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._query_cache_size = query_cache
        self._embed_batch = embed_batch
        self._query_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._runtime = None
        if embedder == "auto":
            self._embedder_state = "starting"
            threading.Thread(target=self._start_runtime, name="cogito-mem-runtime", daemon=True).start()
        elif embedder == "hash":
            self._set_embedder(HashEmbedder())
        elif embedder in (None, "none"):
            self._embedder_state = "none"
        elif isinstance(embedder, str):
            raise ValueError(f"unknown embedder {embedder!r}")
        else:
            self._set_embedder(embedder)

    # ------------------------------------------------------------------ embedder

    def _start_runtime(self) -> None:
        from . import runtime

        try:
            self._runtime = runtime.LlamaRuntime.from_environment(self.root)
            self._runtime.start()
            if self._stop.is_set():  # closed while the model was starting
                self._runtime.stop()
                return
            self._set_embedder(self._runtime.embedder())
        except Exception as exc:  # the memory still works by keyword
            self._embedder_state = f"unavailable: {exc}"
            log.warning("embedding model unavailable, searching by keyword only: %s", exc)

    def set_embedder(self, embedder: Embedder) -> None:
        """Use ``embedder`` from now on (e.g. after loading data without one)."""
        self._set_embedder(embedder)

    def _set_embedder(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._tokenizer = embedder.tokenizer
        self._embedder_state = "ready"
        self._ensure_worker()
        self._wake.set()

    @property
    def embedder(self) -> Embedder | None:
        return self._embedder

    @property
    def tokenizer(self) -> Tokenizer:
        return self._tokenizer

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        """Wait for the embedding model to start. False if it is unavailable or slow."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._embedder_state == "starting":
            if deadline is not None and time.monotonic() > deadline:
                return False
            time.sleep(0.05)
        return self._embedder is not None

    # ------------------------------------------------------------------ namespaces

    def namespace(self, name: str) -> Namespace:
        with self._ns_lock:
            ns = self._namespaces.get(name)
            if ns is None:
                folder = self.root / "memory" / name if self.root is not None else None
                ns = self._namespaces[name] = Namespace(name, folder, index_author=self.config.doc_author)
                if ns.pending:
                    self._ensure_worker()
                    self._wake.set()
            return ns

    def open_all(self) -> None:
        """Open every namespace on disk, so its indexes are built before the first query."""
        for name in self.namespaces():
            self.namespace(name)

    def default_namespace(self) -> str:
        """Where a request without ``namespace`` goes: the name the clients saved, else ``default``."""
        from .names import InvalidName, saved_namespace

        if self.root is None:
            return DEFAULT_NAMESPACE
        try:
            return saved_namespace(self.root) or DEFAULT_NAMESPACE
        except InvalidName as exc:
            raise invalid(str(exc)) from None

    def namespaces(self) -> list[str]:
        names = set(self._namespaces)
        if self.root is not None:
            base = self.root / "memory"
            if base.is_dir():
                names.update(p.name for p in base.iterdir() if (p / "log.sqlite3").exists())
        return sorted(names)

    # ------------------------------------------------------------------ operations

    def handle(self, body: Any) -> dict:
        if not isinstance(body, dict):
            raise invalid("the request must be a JSON object")
        op = body.get("op")
        if body.get("namespace") is None and op in ("append", "query"):
            body = {**body, "namespace": self.default_namespace()}
        if op == "append":
            return self._append(parse_append(body))
        if op == "query":
            return self._query(parse_query(body))
        raise invalid('op must be "append" or "query"')

    def append(self, items: list[dict], namespace: str | None = None, import_: bool = False) -> dict:
        return self.handle({"op": "append", "namespace": namespace, "import": import_, "items": items})

    def query(self, text: str, namespace: str | None = None, **kwargs: Any) -> dict:
        return self.handle({"op": "query", "namespace": namespace, "text": text, **kwargs})

    def _append(self, req: AppendIn) -> dict:
        t0 = time.perf_counter()
        if req.import_:
            limit = timeutil.now_ms() + FUTURE_SKEW_MS
            for i, item in enumerate(req.items):
                if item.valid_at is not None and item.valid_at > limit:
                    raise invalid(f"items[{i}].valid_at is in the future; import loads history only")
        ns = self.namespace(req.namespace)
        results = ns.append(req.items, req.import_, self._tokenizer, self.config.piece_tokens)
        if any(r["status"] == "added" for r in results):
            self._ensure_worker()
            self._wake.set()
        return {"items": results, "took_ms": _ms_since(t0)}

    def _query(self, req: QueryIn) -> dict:
        t0 = time.perf_counter()
        ns = self.namespace(req.namespace)
        if req.as_of is not None:
            as_of = req.as_of
        else:
            # "now" on the memory's own clock: created_at strictly increases, so a burst of
            # appends can run a few milliseconds ahead of the wall clock.
            ns.refresh()
            as_of = max(timeutil.now_ms(), ns.last_live_created)
        candidates = self.candidates(ns, req, as_of)
        items, tokens = ns.fill(
            candidates, req.top_k, req.max_tokens, as_of, req.filter.include_retracted, self._tokenizer
        )
        return {"items": items, "as_of": timeutil.format(as_of), "tokens": tokens, "took_ms": _ms_since(t0)}

    def candidates(self, ns: Namespace, req: QueryIn, as_of: int) -> list[Candidate]:
        cfg = self.config
        pool = max(cfg.candidates, 3 * req.top_k)
        qvec = None
        if cfg.search in ("hybrid", "vector") and self._embedder is not None:
            qvec = self._embed_query(req.text, req.context)
        use_keywords = cfg.search in ("hybrid", "keyword") or qvec is None
        cands = ns.search(req.text, qvec, req.filter, as_of, pool, use_keywords, cfg.rrf_k)
        if self.reranker is not None and cands:
            head = cands[: cfg.candidates]
            scores = self.reranker.score(req.text, [ns.row_text(c.row) for c in head])
            order = sorted(range(len(head)), key=lambda i: -scores[i])
            floor = min(scores) if scores else 0.0
            cands = [Candidate(head[i].row, float(scores[i]), head[i].similarity) for i in order] + [
                Candidate(c.row, c.score * floor, c.similarity) for c in cands[len(head) :]
            ]
        return cands

    def _embed_query(self, text: str, context: str | None) -> np.ndarray:
        profile = getattr(self._embedder, "profile", None)
        prompt = profile.query(text, context) if profile is not None else query_prompt(text, context)
        with self._query_lock:
            vec = self._query_cache.get(prompt)
            if vec is not None:
                self._query_cache.move_to_end(prompt)
                return vec
        assert self._embedder is not None
        vec = self._embedder.embed([prompt])[0]
        with self._query_lock:
            self._query_cache[prompt] = vec
            while len(self._query_cache) > self._query_cache_size:
                self._query_cache.popitem(last=False)
        return vec

    # ------------------------------------------------------------------ background embedding

    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._work, name="cogito-mem-embed", daemon=True)
            self._worker.start()

    def _work(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            if self._embedder is None:
                continue
            while not self._stop.is_set():
                progressed = False
                with self._ns_lock:
                    spaces = list(self._namespaces.values())
                for ns in spaces:
                    try:
                        if self.embed_pending(ns, 512):
                            progressed = True
                        backoff = 0.5
                    except Exception as exc:
                        log.warning("embedding failed in namespace %s: %s", ns.name, exc)
                        time.sleep(backoff)
                        backoff = min(backoff * 2, 30.0)
                if not progressed:
                    break

    def embed_pending(self, ns: Namespace, limit: int = 512, batch: int | None = None) -> int:
        """Give vectors to up to ``limit`` items that have none. Returns how many were done."""
        batch = batch or self._embed_batch
        embedder = self._embedder
        if embedder is None:
            return 0
        rows = ns.take_pending(limit)
        if not rows:
            return 0
        try:
            prompts = ns.prompts(rows, self.config.doc_context, getattr(embedder, "profile", None), self.config.doc_author)
            keys = [cache_key(embedder.name, p) for p in prompts]
            found = self.cache.get_many(keys)
            hit_rows = [r for r, k in zip(rows, keys) if k in found]
            if hit_rows:
                ns.set_vectors(hit_rows, np.stack([found[k] for k in keys if k in found]))
            missing = [(r, p, k) for r, p, k in zip(rows, prompts, keys) if k not in found]
            for i in range(0, len(missing), batch):
                chunk = missing[i : i + batch]
                vecs = embedder.embed([p for _, p, _ in chunk])
                self.cache.put_many([k for _, _, k in chunk], vecs)
                ns.set_vectors([r for r, _, _ in chunk], vecs)
        finally:
            ns.release(rows)
        return len(rows)

    def flush(self, timeout: float | None = None) -> bool:
        """Wait until every stored item has its vector. False if there is no model or on timeout."""
        deadline = None if timeout is None else time.monotonic() + timeout
        if not self.wait_until_ready(timeout):
            return False
        while True:
            with self._ns_lock:
                spaces = list(self._namespaces.values())
            if all(not ns.pending for ns in spaces):
                return True
            if deadline is not None and time.monotonic() > deadline:
                return False
            self._ensure_worker()
            self._wake.set()
            time.sleep(0.01)

    # ------------------------------------------------------------------ info

    def status(self) -> dict:
        embedder = self._embedder
        return {
            "version": __version__,
            "root": str(self.root) if self.root is not None else None,
            "embedder": {
                "name": embedder.name if embedder is not None else None,
                "state": self._embedder_state,
                "tokenizer": self._tokenizer.name,
            },
            "config": {
                "search": self.config.search,
                "doc_context": self.config.doc_context,
                "doc_author": self.config.doc_author,
            },
            "reranker": getattr(self.reranker, "name", None),
            "namespaces": {name: self.namespace(name).stats() for name in self.namespaces()},
        }

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker is not None:
            self._worker.join(timeout=5)
        if self._runtime is not None:
            self._runtime.stop()
        with self._ns_lock:
            for ns in self._namespaces.values():
                ns.close()
            self._namespaces.clear()
        self.cache.close()

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _ms_since(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 3)
