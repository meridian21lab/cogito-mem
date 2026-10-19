"""BM25 keyword index, held in memory and rebuilt from the log on start.

Postings are kept per term as one ``array('i')`` of interleaved (row, term
frequency) pairs, which is compact and can be viewed as a numpy array without a
copy. Rows are the memory's item rows and only ever grow.
"""

from __future__ import annotations

import math
from array import array
from collections import Counter

import numpy as np

from .terms import STOPWORDS, query_terms, terms  # noqa: F401  (part of this module's interface)


class BM25Index:
    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._postings: dict[str, array] = {}
        self._lengths = array("f")
        self._total_length = 0.0
        self._n_docs = 0

    def __len__(self) -> int:
        return len(self._lengths)

    def add(self, row: int, text: str) -> None:
        """Add the item at ``row``. Rows must be added in increasing order without gaps."""
        if row != len(self._lengths):
            raise ValueError(f"rows must be added in order: expected {len(self._lengths)}, got {row}")
        counts = Counter(terms(text))
        length = float(sum(counts.values()))
        self._lengths.append(length)
        self._total_length += length
        self._n_docs += 1
        for term, tf in counts.items():
            postings = self._postings.get(term)
            if postings is None:
                postings = self._postings[term] = array("i")
            postings.append(row)
            postings.append(min(tf, 2**31 - 1))

    def scores(self, query: str, n_rows: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Return (rows, scores) of every item that shares a term with the query."""
        n = len(self._lengths) if n_rows is None else n_rows
        if n == 0:
            return np.empty(0, np.int64), np.empty(0, np.float32)
        q_terms = query_terms(query)
        if not q_terms:
            return np.empty(0, np.int64), np.empty(0, np.float32)
        lengths = np.frombuffer(self._lengths, dtype=np.float32, count=n)
        avg = self._total_length / max(self._n_docs, 1) or 1.0
        acc = np.zeros(n, dtype=np.float32)
        touched = np.zeros(n, dtype=bool)
        for term in q_terms:
            postings = self._postings.get(term)
            if postings is None:
                continue
            pairs = np.frombuffer(postings, dtype=np.int32).reshape(-1, 2)
            rows = pairs[:, 0]
            if n < len(self._lengths):
                rows = rows[rows < n]
                pairs = pairs[: len(rows)]
            df = len(rows)
            if df == 0:
                continue
            idf = math.log(1.0 + (self._n_docs - df + 0.5) / (df + 0.5))
            tf = pairs[:, 1].astype(np.float32)
            denom = tf + self.k1 * (1.0 - self.b + self.b * lengths[rows] / avg)
            acc[rows] += idf * tf * (self.k1 + 1.0) / denom
            touched[rows] = True
        hit = np.flatnonzero(touched)
        return hit, acc[hit]
