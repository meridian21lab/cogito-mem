"""Embedders, prompts and the shared embedding cache.

Every embedder returns vectors cut to their first 256 numbers, normalised, and
rounded to 16 bits (requirements §4, step 5), so a vector read back from the cache
is exactly the vector that was used when it was made.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from .keyword import terms
from .tokenizer import ApproxTokenizer, Tokenizer

DIM = 256
TITLE_MAX_CHARS = 200


def doc_prompt(title: str | None, text: str) -> str:
    """EmbeddingGemma's document prompt (requirements §4)."""
    title = (title or "").strip()[:TITLE_MAX_CHARS] or "none"
    return f"title: {title} | text: {text}"


def query_prompt(text: str, context: str | None = None) -> str:
    """EmbeddingGemma's query prompt; ``context`` is joined to the text (requirements §3.2)."""
    if context:
        text = f"{text}\n{context}"
    return f"task: search result | query: {text}"


@dataclass(frozen=True)
class PromptProfile:
    """How one embedding model wants its documents and queries written.

    EmbeddingGemma is the default and the model v0 ships with. The others let the
    memory run on another GGUF (set COGITO_MEM_MODEL; the profile is picked from the
    file name, or set COGITO_MEM_PROMPTS). Every profile's vectors are cut to 256
    numbers, so only models trained for that (Matryoshka) belong here.
    """

    name: str
    query_prefix: str
    doc_prefix: str
    use_title: bool = True

    def doc(self, title: str | None, text: str) -> str:
        if self.name == "embeddinggemma":
            return doc_prompt(title, text)
        title = (title or "").strip()[:TITLE_MAX_CHARS]
        body = f"{title}\n{text}" if title and self.use_title else text
        return self.doc_prefix + body

    def query(self, text: str, context: str | None = None) -> str:
        if self.name == "embeddinggemma":
            return query_prompt(text, context)
        if context:
            text = f"{text}\n{context}"
        return self.query_prefix + text


PROFILES = {
    "embeddinggemma": PromptProfile("embeddinggemma", "task: search result | query: ", "title: none | text: "),
    "qwen3-embedding": PromptProfile(
        "qwen3-embedding",
        "Instruct: Given a question, retrieve the messages that answer it\nQuery:",
        "",
    ),
    "nomic-embed-text": PromptProfile("nomic-embed-text", "search_query: ", "search_document: "),
}


def profile_for(model_name: str) -> PromptProfile:
    env = os.environ.get("COGITO_MEM_PROMPTS")
    if env:
        if env not in PROFILES:
            raise ValueError(f"COGITO_MEM_PROMPTS must be one of {', '.join(PROFILES)}")
        return PROFILES[env]
    name = model_name.lower()
    if "qwen3-embedding" in name or "qwen3_embedding" in name:
        return PROFILES["qwen3-embedding"]
    if "nomic-embed" in name:
        return PROFILES["nomic-embed-text"]
    return PROFILES["embeddinggemma"]


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
    profile: PromptProfile

    def embed(self, prompts: Sequence[str]) -> np.ndarray:
        """Embed full prompts; returns float32 array of shape (n, DIM) from ``finish``."""
        ...


class HashEmbedder:
    """A deterministic bag-of-words embedder for tests and offline runs.

    It hashes word unigrams and bigrams into 256 signed buckets. It finds shared
    words, not shared meaning, so it is never the default.
    """

    name = "hash-v1"
    profile = PROFILES["embeddinggemma"]

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
