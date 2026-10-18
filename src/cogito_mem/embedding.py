"""Embedders, prompts and the shared embedding cache.

Every embedder returns vectors cut to their first 256 numbers, normalised, and
rounded to 16 bits (requirements §4, step 5), so a vector read back from the cache
is exactly the vector that was used when it was made.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import zlib
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from .keyword import terms
from .tokenizer import ApproxTokenizer, Tokenizer

DIM = 256
TITLE_MAX_CHARS = 200


def doc_prompt(title: str | None, text: str) -> str:
    title = (title or "").strip()[:TITLE_MAX_CHARS] or "none"
    return f"title: {title} | text: {text}"


def query_prompt(text: str, context: str | None = None) -> str:
    if context:
        text = f"{text}\n{context}"
    return f"task: search result | query: {text}"


def finish(raw: np.ndarray) -> np.ndarray:
    """Cut to DIM numbers, normalise, round to float16; returns float32 rows."""
    vecs = np.asarray(raw, dtype=np.float32)
    if vecs.ndim == 1:
        vecs = vecs[None, :]
    if vecs.shape[1] < DIM:
        raise ValueError(f"the model returned {vecs.shape[1]} numbers per vector, need at least {DIM}")
    vecs = vecs[:, :DIM]
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vecs / norms).astype(np.float16).astype(np.float32)


class Embedder(Protocol):
    name: str
    tokenizer: Tokenizer

    def embed(self, prompts: Sequence[str]) -> np.ndarray:
        """Embed full prompts; returns float32 array of shape (n, DIM) from ``finish``."""
        ...


class HashEmbedder:
    """A deterministic bag-of-words embedder for tests and offline runs.

    It hashes word unigrams and bigrams into 256 signed buckets. It finds shared
    words, not shared meaning, so it is never the default.
    """

    name = "hash-v1"

    def __init__(self) -> None:
        self.tokenizer: Tokenizer = ApproxTokenizer()

    @staticmethod
    def _strip_prompt(prompt: str) -> str:
        for prefix in ("task: search result | query: ", "title: none | text: "):
            if prompt.startswith(prefix):
                return prompt[len(prefix):]
        if prompt.startswith("title: "):
            title, _, text = prompt[len("title: "):].partition(" | text: ")
            return f"{title} {text}"
        return prompt

    def embed(self, prompts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(prompts), DIM), dtype=np.float32)
        for i, prompt in enumerate(prompts):
            words = terms(self._strip_prompt(prompt))
            feats = words + [a + " " + b for a, b in zip(words, words[1:])]
            row = out[i]
            for f in feats:
                h = zlib.crc32(f.encode("utf-8"))
                row[h % DIM] += 1.0 if (h >> 16) & 1 else -1.0
            if not feats:
                row[0] = 1.0
        return finish(out)


def cache_key(model: str, prompt: str) -> bytes:
    return hashlib.sha256(model.encode("utf-8") + b"\x00" + prompt.encode("utf-8")).digest()


class EmbeddingCache:
    """Content-addressed vectors: sha256(model, prompt) -> 256 float16 numbers.

    Shared by every namespace, so a text that appears twice is embedded once
    (requirements §5: repeated sessions are embedded once). It is a cache: deleting
    the file only costs re-embedding.
    """

    def __init__(self, path: str | Path | None):
        self._lock = threading.Lock()
        if path is None:
            self._db = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS vectors (key BLOB PRIMARY KEY, vec BLOB NOT NULL) WITHOUT ROWID"
        )
        self._db.commit()

    def get_many(self, keys: Sequence[bytes]) -> dict[bytes, np.ndarray]:
        found: dict[bytes, np.ndarray] = {}
        with self._lock:
            for i in range(0, len(keys), 500):
                chunk = list(keys[i : i + 500])
                marks = ",".join("?" * len(chunk))
                for key, blob in self._db.execute(f"SELECT key, vec FROM vectors WHERE key IN ({marks})", chunk):
                    found[bytes(key)] = np.frombuffer(blob, dtype="<f2").astype(np.float32)
        return found

    def put_many(self, keys: Sequence[bytes], vecs: np.ndarray) -> None:
        rows = [(k, np.asarray(v, dtype="<f2").tobytes()) for k, v in zip(keys, vecs)]
        with self._lock:
            self._db.executemany("INSERT OR IGNORE INTO vectors (key, vec) VALUES (?, ?)", rows)
            self._db.commit()

    def __len__(self) -> int:
        with self._lock:
            return self._db.execute("SELECT count(*) FROM vectors").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._db.close()
