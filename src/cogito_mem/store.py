"""One namespace: its append-only log in SQLite and the indexes built from it.

The log (``log.sqlite3``) is the source of truth. SQLite triggers refuse every
UPDATE and DELETE, so stored text is never edited. Everything else (the keyword
index, the vectors, the row arrays used for filtering) lives in memory and is
rebuilt from the log; vectors come back from the shared embedding cache.

Several processes may open the same namespace. Writes take SQLite's write lock,
and every read first picks up rows other processes added (``refresh``).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np

from . import timeutil
from .api import FilterIn, ItemIn
from .embedding import DIM, PromptProfile, doc_prompt
from .errors import ApiError
from .ids import Uuid7Generator
from .keyword import BM25Index
from .split import PIECE_TOKENS, split
from .tokenizer import Tokenizer, cut

SCHEMA_VERSION = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS log (
    seq        INTEGER PRIMARY KEY,
    id         TEXT    NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    valid_at   INTEGER NOT NULL,
    thread_id  TEXT    NOT NULL,
    author     TEXT    NOT NULL,
    title      TEXT,
    text       TEXT    NOT NULL,
    client_ref TEXT,
    retracts   TEXT    NOT NULL,
    pieces     TEXT    NOT NULL,
    imported   INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS log_client_ref ON log (author, client_ref) WHERE client_ref IS NOT NULL;
CREATE TRIGGER IF NOT EXISTS log_no_update BEFORE UPDATE ON log
    BEGIN SELECT RAISE(ABORT, 'the log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS log_no_delete BEFORE DELETE ON log
    BEGIN SELECT RAISE(ABORT, 'the log is append-only'); END;
"""

KIND_MESSAGE = 0
KIND_PIECE = 1
KIND_CODES = {"message": KIND_MESSAGE, "piece": KIND_PIECE}
KIND_NAMES = {KIND_MESSAGE: "message", KIND_PIECE: "piece"}

NEVER = np.iinfo(np.int64).max
PREVIOUS_CONTEXT_CHARS = 1000


class _Column:
    """A growable numpy column."""

    def __init__(self, dtype, fill=0):
        self.dtype = dtype
        self.fill = fill
        self.data = np.full(1024, fill, dtype=dtype)
        self.n = 0

    def append(self, value) -> None:
        if self.n == len(self.data):
            grown = np.full(len(self.data) * 2, self.fill, dtype=self.dtype)
            grown[: self.n] = self.data[: self.n]
            self.data = grown
        self.data[self.n] = value
        self.n += 1

    def view(self, n: int | None = None) -> np.ndarray:
        return self.data[: self.n if n is None else n]


@dataclass
class Message:
    id: str
    created: int
    valid: int
    thread_id: str
    author: str
    title: str | None
    text: str
    client_ref: str | None
    imported: bool
    rows: list[int] = field(default_factory=list)
    prev: int = -1


@dataclass
class Candidate:
    row: int
    score: float


class Namespace:
    def __init__(self, name: str, folder: Path | None, index_author: bool = False):
        self.name = name
        self.folder = folder
        self.index_author = index_author
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)
            target = str(folder / "log.sqlite3")
        else:
            target = ":memory:"
        self.db = sqlite3.connect(target, check_same_thread=False, isolation_level=None, timeout=60)
        if folder is not None:
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(_SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        self.lock = threading.RLock()

        self.messages: list[Message] = []
        self.msg_by_id: dict[str, int] = {}
        self.refs: dict[tuple[str, str], int] = {}
        self.last_in_thread: dict[str, int] = {}
        self.row_ids: list[str] = []
        self.row_by_id: dict[str, int] = {}
        self._row_msg = _Column(np.int32)
        self._row_start = _Column(np.int32)
        self._row_end = _Column(np.int32)
        self._row_tokens = _Column(np.int32)
        self._row_created = _Column(np.int64)
        self._row_valid = _Column(np.int64)
        self._row_kind = _Column(np.int8)
        self._row_thread = _Column(np.int32)
        self._row_author = _Column(np.int32)
        self._row_retracted = _Column(np.int64, fill=NEVER)
        self._has_vec = _Column(np.bool_, fill=False)
        self._vectors = np.zeros((1024, DIM), dtype=np.float32)
        self.thread_codes: dict[str, int] = {}
        self.author_codes: dict[str, int] = {}
        self.bm25 = BM25Index()
        self.pending: set[int] = set()
        self.in_flight: set[int] = set()
        self.last_seq = 0
        self.last_id: str | None = None
        self.last_live_created = -1
        self.refresh()

    # ------------------------------------------------------------------ loading

    def refresh(self) -> int:
        with self.lock:
            return self._refresh_locked()

    def _refresh_locked(self) -> int:
        cur = self.db.execute(
            "SELECT seq, id, created_at, valid_at, thread_id, author, title, text, client_ref, "
            "retracts, pieces, imported FROM log WHERE seq > ? ORDER BY seq",
            (self.last_seq,),
        )
        added = 0
        for rec in cur:
            self._index(rec)
            added += 1
        return added

    def _code(self, table: dict[str, int], key: str) -> int:
        code = table.get(key)
        if code is None:
            code = table[key] = len(table)
        return code

    def _index(self, rec: tuple) -> None:
        seq, id_, created, valid, thread_id, author, title, text, client_ref, retracts, pieces, imported = rec
        idx = len(self.messages)
        msg = Message(id_, created, valid, thread_id, author, title, text, client_ref, bool(imported))
        msg.prev = self.last_in_thread.get(thread_id, -1)
        self.last_in_thread[thread_id] = idx
        self.messages.append(msg)
        self.msg_by_id[id_] = idx
        if client_ref is not None:
            self.refs[(author, client_ref)] = idx
        thread_code = self._code(self.thread_codes, thread_id)
        author_code = self._code(self.author_codes, author)
        piece_list = json.loads(pieces)
        kind = KIND_MESSAGE if len(piece_list) == 1 and piece_list[0][0] == id_ else KIND_PIECE
        for piece_id, start, end, n_tokens in piece_list:
            row = len(self.row_ids)
            self.row_ids.append(piece_id)
            self.row_by_id[piece_id] = row
            msg.rows.append(row)
            self._row_msg.append(idx)
            self._row_start.append(start)
            self._row_end.append(end)
            self._row_tokens.append(n_tokens)
            self._row_created.append(created)
            self._row_valid.append(valid)
            self._row_kind.append(kind)
            self._row_thread.append(thread_code)
            self._row_author.append(author_code)
            self._row_retracted.append(NEVER)
            self._has_vec.append(False)
            searchable = f"{title}\n{text[start:end]}" if title else text[start:end]
            self.bm25.add(row, f"{author}: {searchable}" if self.index_author else searchable)
            self.pending.add(row)
            self.last_id = piece_id
        for target in json.loads(retracts):
            self._retract(target, created)
        if not imported:
            self.last_live_created = max(self.last_live_created, created)
        self.last_seq = seq

    def _retract(self, target: str, when: int) -> None:
        if target in self.msg_by_id:
            rows = self.messages[self.msg_by_id[target]].rows
        elif target in self.row_by_id:
            rows = [self.row_by_id[target]]
        else:
            return
        data = self._row_retracted.data
        for row in rows:
            if when < data[row]:
                data[row] = when

    # ------------------------------------------------------------------ append

    def append(
        self,
        items: Sequence[ItemIn],
        import_: bool,
        tokenizer: Tokenizer,
        piece_tokens: int = PIECE_TOKENS,
    ) -> list[dict]:
        splits = []
        for item in items:
            known = item.client_ref is not None and (item.author, item.client_ref) in self.refs
            splits.append(None if known else split(item.text, tokenizer, piece_tokens))
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self._refresh_locked()
                results = self._write(items, import_, splits, tokenizer, piece_tokens)
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self._refresh_locked()
        return results

    def _write(self, items, import_, splits, tokenizer, piece_tokens) -> list[dict]:
        gen = Uuid7Generator(self.last_id)
        now = timeutil.now_ms()
        last_live = self.last_live_created
        batch_refs: dict[tuple[str, str], dict] = {}
        batch_ids: set[str] = set()
        results = []
        for i, item in enumerate(items):
            key = (item.author, item.client_ref) if item.client_ref is not None else None
            if key is not None and key in self.refs:
                orig = self.messages[self.refs[key]]
                results.append(
                    {
                        "id": orig.id,
                        "created_at": timeutil.format(orig.created),
                        "status": "duplicate",
                        "pieces": len(orig.rows),
                    }
                )
                continue
            if key is not None and key in batch_refs:
                results.append(dict(batch_refs[key], status="duplicate"))
                continue
            for target in item.retracts:
                if target not in self.msg_by_id and target not in self.row_by_id and target not in batch_ids:
                    raise ApiError("not_found", f"items[{i}].retracts: no item {target} in namespace {self.name!r}")
            spans = splits[i] if splits[i] is not None else split(item.text, tokenizer, piece_tokens)
            if import_:
                created = item.valid_at
            else:
                created = max(now, last_live + 1)
                last_live = created
            valid = item.valid_at if item.valid_at is not None else created
            msg_id = gen.next(now)
            if len(spans) == 1:
                pieces = [[msg_id, 0, len(item.text), spans[0].tokens]]
            else:
                pieces = [[gen.next(now), s.start, s.end, s.tokens] for s in spans]
            self.db.execute(
                "INSERT INTO log (id, created_at, valid_at, thread_id, author, title, text, client_ref, "
                "retracts, pieces, imported) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    msg_id,
                    created,
                    valid,
                    item.thread_id,
                    item.author,
                    item.title,
                    item.text,
                    item.client_ref,
                    json.dumps(item.retracts),
                    json.dumps(pieces),
                    int(import_),
                ),
            )
            batch_ids.add(msg_id)
            batch_ids.update(p[0] for p in pieces)
            result = {"id": msg_id, "created_at": timeutil.format(created), "status": "added", "pieces": len(pieces)}
            if key is not None:
                batch_refs[key] = result
            results.append(result)
        return results

    # ------------------------------------------------------------------ vectors

    def take_pending(self, limit: int) -> list[int]:
        with self.lock:
            rows = sorted(self.pending - self.in_flight)[:limit]
            self.in_flight.update(rows)
            return rows

    def release(self, rows: Sequence[int]) -> None:
        with self.lock:
            self.in_flight.difference_update(rows)

    def set_vectors(self, rows: Sequence[int], vecs: np.ndarray) -> None:
        with self.lock:
            if not len(rows):
                return
            need = max(rows) + 1
            if need > len(self._vectors):
                size = len(self._vectors)
                while size < need:
                    size *= 2
                grown = np.zeros((size, DIM), dtype=np.float32)
                grown[: len(self._vectors)] = self._vectors
                self._vectors = grown
            idx = np.asarray(rows, dtype=np.int64)
            self._vectors[idx] = vecs
            self._has_vec.data[idx] = True
            self.pending.difference_update(rows)
            self.in_flight.difference_update(rows)

    def has_vector(self, item_id: str) -> bool:
        with self.lock:
            row = self.row_by_id.get(item_id)
            if row is None and item_id in self.msg_by_id:
                rows = self.messages[self.msg_by_id[item_id]].rows
                return all(self._has_vec.data[r] for r in rows)
            return row is not None and bool(self._has_vec.data[row])

    def row_text(self, row: int) -> str:
        msg = self.messages[int(self._row_msg.data[row])]
        return msg.text[int(self._row_start.data[row]) : int(self._row_end.data[row])]

    def _previous_text(self, row: int) -> str:
        msg = self.messages[int(self._row_msg.data[row])]
        pos = msg.rows.index(row)
        if pos > 0:
            text = self.row_text(msg.rows[pos - 1])
        elif msg.prev >= 0:
            text = self.messages[msg.prev].text
        else:
            return ""
        if len(text) > PREVIOUS_CONTEXT_CHARS:
            text = text[-PREVIOUS_CONTEXT_CHARS:]
            space = text.find(" ")
            if 0 <= space < 100:
                text = text[space + 1 :]
        return text

    def prompts(
        self,
        rows: Sequence[int],
        doc_context: str = "own",
        profile: PromptProfile | None = None,
        doc_author: bool = False,
    ) -> list[str]:
        write = profile.doc if profile is not None else doc_prompt
        with self.lock:
            out = []
            for row in rows:
                msg = self.messages[int(self._row_msg.data[row])]
                text = self.row_text(row)
                if doc_context == "previous":
                    before = self._previous_text(row)
                    if before:
                        text = f"{before}\n\n{text}"
                if doc_author:
                    text = f"{msg.author}: {text}"
                out.append(write(msg.title, text))
            return out

    # ------------------------------------------------------------------ query

    def _mask(self, flt: FilterIn, as_of: int, n: int) -> np.ndarray:
        mask = self._row_created.view(n) <= as_of
        if not flt.include_retracted:
            mask &= self._row_retracted.view(n) > as_of
        if flt.thread_id is not None:
            code = self.thread_codes.get(flt.thread_id)
            if code is None:
                return np.zeros(n, dtype=bool)
            mask &= self._row_thread.view(n) == code
        if flt.author is not None:
            code = self.author_codes.get(flt.author)
            if code is None:
                return np.zeros(n, dtype=bool)
            mask &= self._row_author.view(n) == code
        if flt.kind is not None:
            codes = [KIND_CODES[k] for k in flt.kind if k in KIND_CODES]
            mask &= np.isin(self._row_kind.view(n), codes)
        if flt.valid_after is not None:
            mask &= self._row_valid.view(n) >= flt.valid_after
        if flt.valid_before is not None:
            mask &= self._row_valid.view(n) < flt.valid_before
        return mask

    @staticmethod
    def _top(rows: np.ndarray, scores: np.ndarray, k: int) -> np.ndarray:
        if len(rows) > k:
            part = np.argpartition(-scores, k - 1)[:k]
            rows, scores = rows[part], scores[part]
        order = np.lexsort((rows, -scores))
        return rows[order]

    def search(
        self,
        text: str,
        qvec: np.ndarray | None,
        flt: FilterIn,
        as_of: int,
        pool: int,
        use_keywords: bool,
        rrf_k: int = 60,
    ) -> list[Candidate]:
        """Rank visible items by reciprocal rank fusion of the vector and keyword lists.

        Scores are normalised so that an item ranked first in every list scores 1.
        """
        with self.lock:
            self._refresh_locked()
            n = len(self.row_ids)
            if n == 0:
                return []
            mask = self._mask(flt, as_of, n)
            ranked: list[np.ndarray] = []
            if qvec is not None:
                idx = np.flatnonzero(mask & self._has_vec.view(n))
                if len(idx):
                    if len(idx) * 4 < n:
                        sims = self._vectors[idx] @ qvec
                    else:
                        sims = (self._vectors[:n] @ qvec)[idx]
                    ranked.append(self._top(idx, sims, pool))
                else:
                    ranked.append(np.empty(0, np.int64))
            if use_keywords:
                rows, scores = self.bm25.scores(text, n)
                keep = mask[rows]
                ranked.append(self._top(rows[keep], scores[keep], pool))
        if not ranked:
            return []
        fused: dict[int, float] = {}
        first_rank: dict[int, int] = {}
        for lst in ranked:
            for rank, row in enumerate(lst.tolist(), start=1):
                fused[row] = fused.get(row, 0.0) + 1.0 / (rrf_k + rank)
                first_rank[row] = min(first_rank.get(row, rank), rank)
        best = len(ranked) / (rrf_k + 1)
        order = sorted(fused, key=lambda r: (-fused[r], first_rank[r], -r))[:pool]
        return [Candidate(r, fused[r] / best) for r in order]

    def fill(
        self,
        candidates: Sequence[Candidate],
        top_k: int,
        max_tokens: int,
        as_of: int,
        include_retracted: bool,
        tokenizer: Tokenizer,
    ) -> tuple[list[dict], int]:
        """Take items in score order within ``top_k`` and the ``max_tokens`` budget (requirements §3.2)."""
        items: list[dict] = []
        total = 0
        with self.lock:
            for cand in candidates:
                if len(items) >= top_k or total >= max_tokens:
                    break
                row = cand.row
                n_tokens = int(self._row_tokens.data[row])
                start = int(self._row_start.data[row])
                end = int(self._row_end.data[row])
                msg = self.messages[int(self._row_msg.data[row])]
                text = msg.text[start:end]
                if not items and n_tokens > max_tokens:
                    text, n_tokens = cut(tokenizer, text, max_tokens)
                    end = start + len(text)
                elif total + n_tokens > max_tokens:
                    continue
                retracted = int(self._row_retracted.data[row])
                expired = timeutil.format(retracted) if include_retracted and retracted <= as_of else None
                items.append(
                    {
                        "id": self.row_ids[row],
                        "kind": KIND_NAMES[int(self._row_kind.data[row])],
                        "text": text,
                        "score": round(float(cand.score), 4),
                        "author": msg.author,
                        "thread_id": msg.thread_id,
                        "valid_at": timeutil.format(msg.valid),
                        "created_at": timeutil.format(msg.created),
                        "expired_at": expired,
                        "source": {"id": msg.id, "title": msg.title, "start": start, "end": end},
                    }
                )
                total += n_tokens
        return items, total

    # ------------------------------------------------------------------ info

    def stats(self) -> dict:
        with self.lock:
            self._refresh_locked()
            n = len(self.row_ids)
            return {
                "messages": len(self.messages),
                "items": n,
                "vectors": int(self._has_vec.view(n).sum()) if n else 0,
                "pending": len(self.pending),
                "tokens": int(self._row_tokens.view(n).sum()) if n else 0,
            }

    def close(self) -> None:
        with self.lock:
            self.db.close()
