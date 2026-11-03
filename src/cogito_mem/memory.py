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
from .api import DEFAULT_NAMESPACE, AppendIn, OpenIn, QueryIn, parse_append, parse_open, parse_query
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
    - ``candidates``: how many fused candidates a reranker (a System-1 model, ``evals/system1.py``)
      reorders (arm R); 0 means every visible item, a full scan ordered by the model alone.
    - ``rerank_context``: what the reranker reads of each candidate: ``"own"`` (author and
      text; default), ``"previous"`` (also the end of the message it follows on from) or
      ``"dated"`` (``"previous"`` with the message's date first). With ``"previous"`` the reply
      after an answer carries the answer in its context and is ranked above it.
    - ``pick``: a probability; when set, the System-1 model picks instead of ordering: only the candidates
      it gives at least this probability of helping are returned (none, if none reaches it).
    - ``rerank_fusion``: ``"replace"`` (default) orders the candidates by the reranker's score
      alone; ``"rrf"`` fuses its ranks with the search's by reciprocal rank, which does worse at
      small budgets on 1M+ token histories (docs/notes/system1_ranker_20261101.md).
    - ``doc_author``: write the author's name before the text for embedding and keyword
      search ("Caroline: …"), so "what did Caroline say about…" finds her messages.
    - ``exact_lane``: also rank the items holding an identifier from the query word for word.
    - ``session_boost``: lift items whose thread has other good matches.

    The defaults are the best arm measured so far (LoCoMo, docs/requirements.md §15):
    hybrid search over items embedded with their author and the message before them.
    """

    search: str = "hybrid"
    doc_context: str = "previous"
    doc_author: bool = True
    candidates: int = 100
    rrf_k: int = 60
    piece_tokens: int = PIECE_TOKENS
    rerank_context: str = "own"
    rerank_fusion: str = "replace"
    exact_lane: bool = False
    session_boost: float = 0.0
    pick: float | None = None

    def __post_init__(self) -> None:
        if self.search not in ("hybrid", "vector", "keyword"):
            raise ValueError(f"search must be hybrid, vector or keyword, not {self.search!r}")
        if self.doc_context not in ("own", "previous"):
            raise ValueError(f"doc_context must be own or previous, not {self.doc_context!r}")
        if self.rerank_context not in ("own", "previous", "dated"):
            raise ValueError(f"rerank_context must be own, previous or dated, not {self.rerank_context!r}")
        if self.pick is not None and not 0.0 <= self.pick <= 1.0:
            raise ValueError(f"pick must be a probability between 0 and 1, not {self.pick!r}")
        if self.rerank_fusion not in ("replace", "rrf"):
            raise ValueError(f"rerank_fusion must be replace or rrf, not {self.rerank_fusion!r}")


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
        if body.get("namespace") is None and op in ("append", "query", "open"):
            body = {**body, "namespace": self.default_namespace()}
        if op == "append":
            return self._append(parse_append(body))
        if op == "query":
            return self._query(parse_query(body))
        if op == "open":
            return self._open(parse_open(body))
        raise invalid('op must be "append", "query" or "open"')

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

    def _open(self, req: OpenIn) -> dict:
        t0 = time.perf_counter()
        ns = self.namespace(req.namespace)
        msg = ns.find_message(req.id)
        if msg is None:
            raise ApiError("not_found", f"no message {req.id} in namespace {req.namespace!r}")
        items = ns.around(msg, req.before, req.after, req.max_tokens, self._tokenizer, max(timeutil.now_ms(), ns.last_live_created))
        if items is None:
            raise ApiError("not_found", f"no message {req.id} in namespace {req.namespace!r}")
        return {"items": items, "took_ms": _ms_since(t0)}

    def candidates(self, ns: Namespace, req: QueryIn, as_of: int) -> list[Candidate]:
        cfg = self.config
        pool = max(cfg.candidates, 3 * req.top_k)
        qvec = None
        if cfg.search in ("hybrid", "vector") and self._embedder is not None:
            qvec = self._embed_query(req.text, req.context)
        use_keywords = cfg.search in ("hybrid", "keyword") or qvec is None
        cands = ns.search(req.text, qvec, req.filter, as_of, pool, use_keywords, cfg.rrf_k, cfg.exact_lane, cfg.session_boost)
        if self.reranker is None or req.rerank == 0:
            return cands
        candidates = cfg.candidates if req.rerank is None else req.rerank
        if candidates <= 0:  # full scan: the reranker reads every visible item
            found = {c.row for c in cands}
            cands = cands + [Candidate(int(r), 0.0) for r in ns.visible(req.filter, as_of) if int(r) not in found]
        if not cands:
            return cands
        head = cands if candidates <= 0 else cands[:candidates]
        scores = self.reranker.score(req.text, ns.rank_texts([c.row for c in head], cfg.rerank_context))
        if cfg.pick is not None:
            # The System-1 model decides: a candidate is returned only if its probability of helping reaches
            # ``pick``, most confident first; the rest, and everything it did not read, are left out.
            kept = sorted((i for i in range(len(head)) if scores[i] >= cfg.pick), key=lambda i: (-scores[i], i))
            return [Candidate(head[i].row, float(scores[i]), head[i].similarity) for i in kept]
        # A full scan has no search order to fuse with (items past the keyword matches come oldest first).
        if cfg.rerank_fusion == "rrf" and candidates > 0:
            by_model = sorted(range(len(head)), key=lambda i: (-scores[i], i))
            model_rank = {i: r for r, i in enumerate(by_model, start=1)}
            best = 2 / (cfg.rrf_k + 1)
            scores = [(1 / (cfg.rrf_k + i + 1) + 1 / (cfg.rrf_k + model_rank[i])) / best for i in range(len(head))]
        # A tie (the search and the model swapped two items) keeps the search's order: on the development
        # questions this was a little better than letting the model break it.
        order = sorted(range(len(head)), key=lambda i: (-scores[i], i))
        floor = min(scores) if scores else 0.0
        return [Candidate(head[i].row, float(scores[i]), head[i].similarity) for i in order] + [
            Candidate(c.row, c.score * floor, c.similarity) for c in cands[len(head) :]
        ]

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
                "candidates": self.config.candidates,
                "rerank_context": self.config.rerank_context,
                "rerank_fusion": self.config.rerank_fusion,
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
