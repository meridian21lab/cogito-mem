"""Building blocks: time, ids, tokenizer, splitting, BM25, embeddings, storage."""

from __future__ import annotations

import sqlite3
import uuid

import numpy as np
import pytest
from conftest import append, query

from cogito_mem import Memory, timeutil
from cogito_mem.embedding import DIM, EmbeddingCache, HashEmbedder, cache_key, doc_prompt, finish, query_prompt
from cogito_mem.ids import Uuid7Generator
from cogito_mem.keyword import BM25Index, terms
from cogito_mem.split import split
from cogito_mem.tokenizer import ApproxTokenizer, cut, tokens_in


# --------------------------------------------------------------------------- time and ids


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-10-14T16:00:00Z", "2026-10-14T16:00:00.000Z"),
        ("2026-10-14T16:00:00.031Z", "2026-10-14T16:00:00.031Z"),
        ("2026-10-14T16:00:00.0319999Z", "2026-10-14T16:00:00.031Z"),
        ("2026-10-14T18:00:00+02:00", "2026-10-14T16:00:00.000Z"),
        ("2026-10-14T11:30:00-04:30", "2026-10-14T16:00:00.000Z"),
        ("2026-10-14 16:00:00z", "2026-10-14T16:00:00.000Z"),
        ("1969-12-31T23:59:59.500Z", "1969-12-31T23:59:59.500Z"),
    ],
)
def test_rfc3339_round_trip(text, expected):
    assert timeutil.format(timeutil.parse(text)) == expected


@pytest.mark.parametrize("bad", ["2026-10-14", "2026-10-14T16:00:00", "2026-13-01T00:00:00Z", "yesterday", ""])
def test_rfc3339_rejects(bad):
    with pytest.raises(ValueError):
        timeutil.parse(bad)


def test_uuid7_is_monotonic_within_and_across_milliseconds():
    gen = Uuid7Generator()
    ids = [gen.next(1_792_000_000_000) for _ in range(5000)] + [gen.next(1_792_000_000_001 + i) for i in range(10)]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert all(uuid.UUID(i).version == 7 and uuid.UUID(i).variant == uuid.RFC_4122 for i in ids)
    # a generator resumed from the last id continues after it, even if the clock went back
    resumed = Uuid7Generator(ids[-1])
    assert resumed.next(1_000) > ids[-1]
    assert uuid.UUID(ids[0]).int >> 80 == 1_792_000_000_000


# --------------------------------------------------------------------------- tokenizer and splitting


def test_approx_tokenizer_offsets():
    tok = ApproxTokenizer()
    text = "Hello world, 2026 你好\n\nsupercalifragilistic"
    ends = tok.offsets(text)
    assert ends == sorted(ends) and ends[-1] == len(text)
    assert 12 <= len(ends) <= 20
    assert tokens_in(ends, 0, len(text)) == len(ends)
    prefix, n = cut(tok, text, 3)
    assert n == 3 and text.startswith(prefix) and prefix == "Hello world,"


def test_short_message_is_one_span():
    tok = ApproxTokenizer()
    spans = split("A short message.", tok)
    assert len(spans) == 1 and (spans[0].start, spans[0].end) == (0, 16)


def test_split_prefers_paragraphs_then_sentences_and_respects_limit():
    tok = ApproxTokenizer()
    para = " ".join(f"Sentence {i} has a few plain words in it." for i in range(12))  # ~120 tokens
    text = "\n\n".join([para, para, "Tiny paragraph.", para, " ".join([para] * 4)])
    spans = split(text, tok, 256)
    assert len(spans) > 2
    covered = []
    for s in spans:
        piece = text[s.start : s.end]
        assert piece == piece.strip() and piece
        assert len(tok.offsets(piece)) <= 256
        assert s.tokens <= 256
        covered.append(piece)
    # no text is lost: everything except whitespace is in some piece, in order
    assert "".join("".join(covered).split()) == "".join(text.split())
    # the first two paragraphs fit together, so the first piece ends at a paragraph break
    assert text[spans[0].end : spans[0].end + 2] == "\n\n"


def test_split_hard_splits_a_giant_sentence():
    tok = ApproxTokenizer()
    text = "x" + "y" * 5000  # one word, many tokens, no breaks at all
    spans = split(text, tok, 256)
    assert len(spans) > 1
    assert "".join(text[s.start : s.end] for s in spans) == text
    assert all(len(tok.offsets(text[s.start : s.end])) <= 256 for s in spans)


# --------------------------------------------------------------------------- BM25


def test_bm25_ranks_rare_terms_higher():
    idx = BM25Index()
    docs = ["the cat sat", "the dog sat", "the cat and the zebra", "a zebra crossing"]
    for i, d in enumerate(docs):
        idx.add(i, d)
    rows, scores = idx.scores("zebra cat")
    ranked = [int(r) for r in rows[np.argsort(-scores)]]
    assert ranked[0] == 2  # has both terms
    assert set(ranked) == {0, 2, 3}
    rows, _ = idx.scores("unknownword")
    assert len(rows) == 0
    rows, _ = idx.scores("zebra", n_rows=3)  # an older view of the index
    assert [int(r) for r in rows] == [2]


def test_terms_handle_unicode():
    assert terms("Café LATTE, naïve 東京") == ["café", "latte", "naïve", "東", "京"]


# --------------------------------------------------------------------------- embeddings


def test_finish_cuts_normalises_and_rounds():
    raw = np.random.default_rng(0).standard_normal((3, 768)).astype(np.float32)
    out = finish(raw)
    assert out.shape == (3, DIM) and out.dtype == np.float32
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-3)
    assert np.array_equal(out, out.astype(np.float16).astype(np.float32))
    with pytest.raises(ValueError):
        finish(np.ones((1, 128)))


def test_prompts():
    assert doc_prompt(None, "hi") == "title: none | text: hi"
    assert doc_prompt("Jana's report", "hi") == "title: Jana's report | text: hi"
    assert query_prompt("q?") == "task: search result | query: q?"
    assert query_prompt("q?", "ctx") == "task: search result | query: q?\nctx"


def test_hash_embedder_is_deterministic_and_lexical():
    emb = HashEmbedder()
    a, b, c = emb.embed([query_prompt("apple pie"), doc_prompt(None, "apple pie recipe"), doc_prompt(None, "car")])
    assert float(a @ b) > float(a @ c)
    assert np.array_equal(emb.embed([query_prompt("apple pie")])[0], a)


def test_embedding_cache(tmp_path):
    cache = EmbeddingCache(tmp_path / "c.sqlite3")
    vecs = HashEmbedder().embed(["a", "b"])
    keys = [cache_key("m", "a"), cache_key("m", "b")]
    cache.put_many(keys, vecs)
    cache.put_many(keys, vecs)  # idempotent
    got = cache.get_many(keys + [cache_key("other-model", "a")])
    assert len(got) == 2 and np.array_equal(got[keys[0]], vecs[0])
    assert len(cache) == 2
    cache.close()


def test_vectors_come_back_from_the_cache_without_re_embedding(tmp_path):
    class Counting(HashEmbedder):
        calls = 0

        def embed(self, prompts):
            Counting.calls += len(prompts)
            return super().embed(prompts)

    root = tmp_path / "home"
    with Memory(root, embedder=Counting()) as m:
        append(m, {"author": "a", "text": "remember the milk"}, {"author": "a", "text": "and the eggs"})
        assert m.flush(10)
    first = Counting.calls
    assert first == 2
    with Memory(root, embedder=Counting()) as m:  # reopen: vectors are read from the cache
        m.namespace("default")
        assert m.flush(10)
        assert m.namespace("default").stats()["vectors"] == 2
    assert Counting.calls == first


# --------------------------------------------------------------------------- storage


def test_log_persists_and_is_append_only(tmp_path):
    root = tmp_path / "home"
    with Memory(root, embedder=None) as m:
        r = append(m, {"author": "a", "text": "persist me", "client_ref": "p1"})["items"][0]
    db_path = root / "memory" / "default" / "log.sqlite3"
    assert db_path.exists()
    db = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("UPDATE log SET text = 'changed'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("DELETE FROM log")
    db.close()
    with Memory(root, embedder=None) as m:
        again = append(m, {"author": "a", "text": "persist me", "client_ref": "p1"})["items"][0]
        assert again["status"] == "duplicate" and again["id"] == r["id"]
        assert query(m, "persist")["items"][0]["text"] == "persist me"
        later = append(m, {"author": "a", "text": "after reopen"})["items"][0]
        assert later["id"] > r["id"] and later["created_at"] > r["created_at"]


def test_two_memories_on_one_folder_see_each_others_appends(tmp_path):
    root = tmp_path / "home"
    a = Memory(root, embedder="hash")
    b = Memory(root, embedder="hash")
    try:
        append(a, {"author": "a", "text": "written by the first process", "client_ref": "x"})
        assert query(b, "first process")["items"][0]["text"] == "written by the first process"
        # dedup and created_at order hold across both writers
        assert append(b, {"author": "a", "text": "again", "client_ref": "x"})["items"][0]["status"] == "duplicate"
        r1 = append(b, {"author": "b", "text": "from b"})["items"][0]
        r2 = append(a, {"author": "a", "text": "from a"})["items"][0]
        assert r2["created_at"] > r1["created_at"] and r2["id"] > r1["id"]
    finally:
        a.close()
        b.close()


def test_keyword_search_works_without_any_model(tmp_path):
    with Memory(tmp_path / "home", embedder=None) as m:
        append(m, {"author": "a", "text": "the quarterly budget review is on Thursday"})
        resp = query(m, "budget review")
        assert resp["items"][0]["text"].startswith("the quarterly budget")
        assert m.status()["embedder"]["state"] == "none"
        assert m.flush(0.1) is False


def test_status_lists_namespaces(tmp_path):
    with Memory(tmp_path / "home", embedder="hash") as m:
        append(m, {"author": "a", "text": "one"}, namespace="alpha")
        append(m, {"author": "a", "text": "two"}, namespace="beta")
        m.flush(10)
        info = m.status()
        assert set(info["namespaces"]) == {"alpha", "beta"}
        assert info["namespaces"]["alpha"]["messages"] == 1
        assert info["embedder"] == {"name": "hash-v1", "state": "ready", "tokenizer": "approx-v1"}


def test_previous_message_context_changes_document_vectors(tmp_path):
    from cogito_mem import Config

    with Memory(None, embedder="hash", config=Config(doc_context="previous")) as m:
        append(
            m,
            {"author": "user", "thread_id": "s", "text": "What should we name the squirrel?"},
            {"author": "assistant", "thread_id": "s", "text": "Cogi."},
        )
        ns = m.namespace("default")
        prompts = ns.prompts([0, 1], "previous")
        assert prompts[0] == "title: none | text: What should we name the squirrel?"
        assert prompts[1] == "title: none | text: What should we name the squirrel?\n\nCogi."
        assert ns.prompts([1], "own") == ["title: none | text: Cogi."]


def test_prompt_profiles_follow_the_model(monkeypatch):
    from cogito_mem.embedding import PROFILES, profile_for

    monkeypatch.delenv("COGITO_MEM_PROMPTS", raising=False)
    assert profile_for("embeddinggemma-2-Q8_0.gguf").doc(None, "x") == "title: none | text: x"
    qwen = profile_for("qwen3-embedding-0.6B-Q8_0.gguf")
    assert qwen.query("q?").startswith("Instruct: ") and qwen.query("q?").endswith("\nQuery:q?")
    assert qwen.doc("Report", "x") == "Report\nx" and qwen.doc(None, "x") == "x"
    assert profile_for("nomic-embed-text-v1.5.f16.gguf").query("q") == "search_query: q"
    monkeypatch.setenv("COGITO_MEM_PROMPTS", "qwen3-embedding")
    assert profile_for("anything.gguf") is PROFILES["qwen3-embedding"]
    monkeypatch.setenv("COGITO_MEM_PROMPTS", "nope")
    with pytest.raises(ValueError):
        profile_for("x")


def test_doc_author_puts_the_speaker_into_search(tmp_path):
    from cogito_mem import Config

    with Memory(None, embedder="hash", config=Config(doc_author=True)) as m:
        append(m, {"author": "Caroline", "text": "I researched adoption agencies."}, {"author": "Mel", "text": "I went camping."})
        assert m.namespace("default").prompts([0], "own", None, True) == [
            "title: none | text: Caroline: I researched adoption agencies."
        ]
        items = query(m, "What did Caroline research?", max_tokens=1000)["items"]
        assert items[0]["text"] == "I researched adoption agencies."  # the stored text is unchanged
    with Memory(None, embedder="hash") as m:  # off by default
        append(m, {"author": "Caroline", "text": "I went hiking."})
        assert query(m, "Caroline")["items"] == []
