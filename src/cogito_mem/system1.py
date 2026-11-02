"""System-1 ranking: a small local decision model reads the question and each candidate memory.

The search (BM25 and EmbeddingGemma) finds candidates by words and meaning; a System-1 model
then reads the question and a candidate together and says how likely the candidate helps answer
it. The idea and the request shape come from TypeSafe's Jev ("System One"): a state plus named,
typed questions, answered with probabilities and no generated text. Jev itself is a hosted model,
so cogito-mem only uses open-weight models that llama.cpp runs on the user's machine:

- ``rerank``: a pointwise reranker LLM through ``llama-server --reranking`` (``/v1/rerank``),
  e.g. Qwen3-Reranker-0.6B: P("yes") that the document meets the query, a Jev *Noul*.
- ``noul``: a native decision model through llama.cpp's TypeSafe-compatible ``/v1/systemone``
  (e.g. vLLM-SR's d3), one Noul question per candidate: "does this message help answer …?".
- ``choice``: the same decision model, one Choice question whose options are the candidates;
  one forward pass gives a probability for every candidate (listwise).

Every scorer has the ``Reranker`` shape of ``memory.py``: ``score(query, texts)`` returns one
number in [0, 1] per text, higher is more relevant. Nothing leaves the machine: the servers listen
on 127.0.0.1 only. See docs/notes/system1_ranker_20261101.md for the spec and the measurements.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Sequence

from .runtime import LlamaServer, LlamaServerReranker, RuntimeUnavailable, _post, find_llama_server

KINDS = ("rerank", "noul", "choice")

# The question each candidate is judged against (Jev's "instructions"). Worded for a memory of
# chat messages: the candidate is one earlier message, and it counts when it holds part of the answer.
NOUL_INSTRUCTION = (
    "Does the message contain information that helps answer the question, even partly? "
    "The message is from the user's earlier conversations with an AI assistant."
)
CHOICE_INSTRUCTION = (
    "Which earlier message from the user's conversations with an AI assistant best helps "
    "answer the question?"
)
# A d3 prompt is evaluated in one batch, so a Choice over many long candidates must fit in it.
CHOICE_MAX_OPTIONS = 255
DECISION_UBATCH = 16384
# A pointwise model is sent at most this many texts a request: a full scan or a long candidate list on a CPU would
# otherwise run past the HTTP timeout (about 400 tokens a second for a 0.6B model on 4 cores).
POINTWISE_CHUNK = 32


class SystemOneRanker:
    """Ranks candidates with a decision model served by llama.cpp's ``/v1/systemone``.

    ``mode="noul"`` asks one Noul question per candidate (the state holds the question and the
    candidate); ``mode="choice"`` asks one Choice question over all candidates (the state is the
    question, the options are the candidates). Noul requests run ``workers`` at a time, so the
    server's parallel slots stay busy.
    """

    def __init__(self, base: str, name: str, mode: str = "noul", workers: int = 4,
                 noul_instruction: str = NOUL_INSTRUCTION, choice_instruction: str = CHOICE_INSTRUCTION):  # fmt: skip
        if mode not in ("noul", "choice"):
            raise ValueError(f"mode must be noul or choice, not {mode!r}")
        self.base = base
        self.mode = mode
        self.name = f"{name}:{mode}"
        self.workers = workers
        self.noul_instruction = noul_instruction
        self.choice_instruction = choice_instruction
        self._pool = ThreadPoolExecutor(max_workers=workers) if mode == "noul" and workers > 1 else None

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        if self.mode == "choice":
            return self._choice(query, list(texts))
        if self._pool is None:
            return [self._noul(query, t) for t in texts]
        return list(self._pool.map(lambda t: self._noul(query, t), texts))

    def _noul(self, query: str, text: str) -> float:
        body = {"state": {"question": query, "message": text},
                "questions": {"helps": {"type": "noul", "instructions": self.noul_instruction}}}  # fmt: skip
        res = _post(self.base, "/v1/systemone", body)
        return float(res["answers"]["helps"]["noul"])  # type: ignore[index]

    def _choice(self, query: str, texts: list[str]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(texts), CHOICE_MAX_OPTIONS):
            chunk = texts[start : start + CHOICE_MAX_OPTIONS]
            options = {str(i + 1): t for i, t in enumerate(chunk)}
            body = {"state": {"question": query},
                    "questions": {"best": {"type": "choice", "instructions": self.choice_instruction,
                                           "criteria": options}}}  # fmt: skip
            res = _post(self.base, "/v1/systemone", body, timeout=600.0)
            probs = res["answers"]["best"]["probabilities"]  # type: ignore[index]
            scores += [float(probs.get(str(i + 1), 0.0)) for i in range(len(chunk))]
        return scores


class ScoreCache:
    """Scores already computed, keyed by scorer, question and candidate text (SQLite, or memory only).

    The scores of a model do not change, so an evaluation that asks the same question at several
    budgets, or reruns with another fusion, reads them back instead of running the model again.
    """

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path) if self.path else ":memory:", check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS scores (key TEXT PRIMARY KEY, score REAL NOT NULL)")
        self._lock = threading.Lock()

    @staticmethod
    def key(scorer: str, query: str, text: str) -> str:
        return hashlib.sha256(json.dumps([scorer, query, text]).encode("utf-8")).hexdigest()

    def get_many(self, keys: Sequence[str]) -> dict[str, float]:
        found: dict[str, float] = {}
        with self._lock:
            for i in range(0, len(keys), 500):
                chunk = list(keys[i : i + 500])
                marks = ",".join("?" * len(chunk))
                found.update(self._db.execute(f"SELECT key, score FROM scores WHERE key IN ({marks})", chunk))
        return found

    def put_many(self, pairs: Sequence[tuple[str, float]]) -> None:
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO scores VALUES (?, ?)", pairs)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


class CachedRanker:
    """A ranker whose scores are kept in a ``ScoreCache``; ``stats`` counts what ran and for how long.

    A Choice score depends on the other options, so for a listwise (``choice``) ranker the key of
    each option also holds the whole list of options.
    """

    def __init__(self, ranker, cache: ScoreCache):
        self.ranker = ranker
        self.cache = cache
        self.name = ranker.name
        self.listwise = getattr(ranker, "mode", None) == "choice"
        self.stats = {"calls": 0, "scored": 0, "cached": 0, "model_s": 0.0}

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        self.stats["calls"] += 1
        context = query
        if self.listwise:
            context = query + "\x00" + hashlib.sha256(json.dumps(list(texts)).encode("utf-8")).hexdigest()
        keys = [ScoreCache.key(self.name, context, t) for t in texts]
        found = self.cache.get_many(keys)
        todo = [i for i, k in enumerate(keys) if k not in found]
        if self.listwise and todo:
            todo = list(range(len(texts)))
        self.stats["cached"] += len(texts) - len(todo)
        if todo:
            t0 = time.perf_counter()
            if self.listwise:  # a Choice's probabilities depend on the whole list
                new = self.ranker.score(query, [texts[i] for i in todo])
            else:
                new = []
                for start in range(0, len(todo), POINTWISE_CHUNK):
                    new += self.ranker.score(query, [texts[i] for i in todo[start : start + POINTWISE_CHUNK]])
            self.stats["model_s"] += time.perf_counter() - t0
            self.stats["scored"] += len(todo)
            self.cache.put_many([(keys[i], float(v)) for i, v in zip(todo, new)])
            found.update({keys[i]: float(v) for i, v in zip(todo, new)})
        return [found[k] for k in keys]


def start_system1(spec: str, kind: str, root: Path | None = None, threads: int | None = None,
                  ) -> tuple[object, LlamaServer | None]:  # fmt: skip
    """Start (or connect to) a System-1 scorer. ``spec`` is a GGUF path or a running llama-server URL.

    ``kind`` is ``rerank`` (``--reranking`` and ``/v1/rerank``), ``noul`` or ``choice``
    (``/v1/systemone``, which llama.cpp serves for native decision models).
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}, not {kind!r}")
    if spec.startswith(("http://", "https://")):
        base = spec.rstrip("/")
        server = None
        name = spec
    else:
        binary = find_llama_server(root)
        if binary is None:
            raise RuntimeUnavailable("llama-server was not found for the System-1 model")
        model = Path(spec).expanduser()
        if not model.exists():
            raise RuntimeUnavailable(f"System-1 model {model} does not exist")
        if kind == "rerank":
            extra = ["--reranking"]
        else:
            # a d3 prompt (all the options of a Choice) is evaluated in one batch
            extra = ["-c", str(DECISION_UBATCH * 2), "-b", str(DECISION_UBATCH), "-ub", str(DECISION_UBATCH),
                     "--parallel", "2"]  # fmt: skip
        if threads:
            extra += ["-t", str(threads)]
        log_path = root / "run" / "llama-system1.log" if root is not None else None
        server = LlamaServer(binary, model, extra, log_path)
        server.start()
        base = server.base
        name = model.name
    if kind == "rerank":
        return LlamaServerReranker(base, name), server
    return SystemOneRanker(base, name, mode=kind), server
