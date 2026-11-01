"""System-1 ranking (system1.py): local decision models behind the search, with fake llama-servers."""

from __future__ import annotations

import json
import threading
from collections import Counter
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

from conftest import append, query

from cogito_mem.evals.longmemeval_recall import stratified_order
from cogito_mem.memory import Config, Memory
from cogito_mem.system1 import CachedRanker, ScoreCache, SystemOneRanker


class _FakeSystemOne(BaseHTTPRequestHandler):
    """/v1/systemone: a message "helps" when it names Biscuit; a choice puts its mass on such options."""

    requests: list[dict] = []

    def do_POST(self):  # noqa: N802
        assert self.path == "/v1/systemone"
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append(body)
        answers = {}
        for qid, q in body["questions"].items():
            if q["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": 0.9 if "Biscuit" in body["state"]["message"] else 0.1}
            else:
                weights = {k: (9.0 if "Biscuit" in v else 1.0) for k, v in q["criteria"].items()}
                total = sum(weights.values())
                probs = {k: w / total for k, w in weights.items()}
                answers[qid] = {"type": "choice", "choice": max(probs, key=probs.get), "probabilities": probs}
        data = json.dumps({"model": "fake-d3", "answers": answers}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@contextmanager
def fake_systemone():
    _FakeSystemOne.requests = []
    srv = HTTPServer(("127.0.0.1", 0), _FakeSystemOne)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


class _Counting:
    """A pointwise ranker that counts the texts it is asked to score."""

    name = "counting"

    def __init__(self):
        self.seen: list[str] = []

    def score(self, query, texts):
        self.seen += list(texts)
        return [0.9 if "Biscuit" in t else 0.1 for t in texts]


def test_noul_asks_one_question_per_candidate():
    with fake_systemone() as base:
        ranker = SystemOneRanker(base, "fake-d3", mode="noul", workers=2)
        assert ranker.score("dog name", ["user: My dog is Biscuit", "user: a cat"]) == [0.9, 0.1]
        assert len(_FakeSystemOne.requests) == 2
        body = _FakeSystemOne.requests[0]
        assert body["state"]["question"] == "dog name" and list(body["questions"]) == ["helps"]
        assert ranker.name == "fake-d3:noul"


def test_choice_reads_all_candidates_in_one_request():
    with fake_systemone() as base:
        ranker = SystemOneRanker(base, "fake-d3", mode="choice")
        scores = ranker.score("dog name", ["user: a cat", "user: My dog is Biscuit", "user: a fish"])
        assert len(_FakeSystemOne.requests) == 1
        assert scores[1] == max(scores) and abs(sum(scores) - 1) < 1e-9
        assert list(_FakeSystemOne.requests[0]["questions"]["best"]["criteria"]) == ["1", "2", "3"]


def test_cached_ranker_scores_each_text_once(tmp_path):
    inner = _Counting()
    ranker = CachedRanker(inner, ScoreCache(tmp_path / "scores.sqlite3"))
    assert ranker.score("q", ["Biscuit", "cat"]) == [0.9, 0.1]
    assert ranker.score("q", ["cat", "fish", "Biscuit"]) == [0.1, 0.1, 0.9]
    assert inner.seen == ["Biscuit", "cat", "fish"]
    assert ranker.stats["scored"] == 3 and ranker.stats["cached"] == 2
    again = CachedRanker(_Counting(), ScoreCache(tmp_path / "scores.sqlite3"))  # survives a restart
    assert again.score("q", ["fish"]) == [0.1] and again.ranker.seen == []


def test_cached_choice_depends_on_the_whole_list(tmp_path):
    with fake_systemone() as base:
        ranker = CachedRanker(SystemOneRanker(base, "fake-d3", mode="choice"), ScoreCache(None))
        a = ranker.score("q", ["Biscuit", "cat"])
        assert ranker.score("q", ["Biscuit", "cat"]) == a and len(_FakeSystemOne.requests) == 1
        b = ranker.score("q", ["Biscuit", "cat", "fish"])  # another list: the probabilities change
        assert len(_FakeSystemOne.requests) == 2 and b[0] != a[0]


def items(m: Memory) -> None:
    append(m, {"author": "user", "thread_id": "s1", "text": "dog name ideas: Rex, Max, dog dog"},
           {"author": "assistant", "thread_id": "s1", "text": "Both are good dog names."},
           {"author": "user", "thread_id": "s2", "text": "We adopted a beagle and named him Biscuit"},
           {"author": "user", "thread_id": "s3", "text": "The weather is nice today"})  # fmt: skip
    m.flush(10)


def test_reranker_reads_author_and_the_message_before():
    inner = _Counting()
    with Memory(None, embedder="hash", reranker=inner, config=Config(search="keyword", rerank_context="previous")) as m:
        items(m)
        query(m, "dog names")
        assert "user: dog name ideas: Rex, Max, dog dog\nassistant: Both are good dog names." in inner.seen
    inner = _Counting()
    with Memory(None, embedder="hash", reranker=inner, config=Config(search="keyword")) as m:  # default: own
        items(m)
        query(m, "dog names")
        assert "assistant: Both are good dog names." in inner.seen


def test_full_scan_scores_every_visible_item():
    inner = _Counting()
    with Memory(None, embedder="hash", reranker=inner, config=Config(search="keyword", candidates=0)) as m:
        items(m)
        got = query(m, "dog names")["items"]
        assert len(inner.seen) == 4  # the keyword search matches 2; the full scan reads all 4
        assert got[0]["text"] == "We adopted a beagle and named him Biscuit"  # found with no shared word


def test_rrf_fusion_keeps_part_of_the_search_order():
    with Memory(None, embedder="hash", reranker=_Counting(), config=Config(search="keyword")) as m:  # rrf: default
        items(m)
        got = query(m, "dog names")["items"]
        assert [i["score"] for i in got] == sorted((i["score"] for i in got), reverse=True)
        assert 0 < got[0]["score"] <= 1


def test_dated_context_puts_the_date_first():
    with Memory(None, embedder="hash") as m:
        append(m, {"author": "user", "text": "Biscuit", "valid_at": "2024-03-05T10:00:00Z"}, import_=True)
        ns = m.namespace("default")
        assert ns.rank_texts([0], "dated") == ["[2024-03-05] user: Biscuit"]
        assert ns.rank_texts([0], "own") == ["user: Biscuit"]


def test_stratified_sample_keeps_the_type_mix_and_nests():
    qs = [{"question_id": f"{t}-{i}", "question_type": t} for t, n in (("a", 60), ("b", 30), ("c", 10)) for i in range(n)]
    order = stratified_order(qs, seed=0)
    assert Counter(q["question_type"] for q in order[:20]) == {"a": 12, "b": 6, "c": 2}
    assert order[:20] == stratified_order(qs, seed=0)[:20]  # deterministic
    assert [q["question_id"] for q in order[:10]] == [q["question_id"] for q in order[:20][:10]]
    assert order != stratified_order(qs, seed=1)


def test_long_history_runs_a_system1_rerank_variant(tmp_path):
    from test_evals import long_history_question

    from cogito_mem.evals import long_history

    data = tmp_path / "m.json"
    data.write_text(json.dumps([long_history_question(sessions=30)]))
    out = tmp_path / "r.json"
    log = tmp_path / "q.jsonl"
    with fake_systemone() as base:
        args = ["run", "--data", str(data), "--search", "keyword", "--variants", "base", "--system1", base,
                "--system1-kind", "noul", "--candidates", "10", "--questions-out", str(log), "--out", str(out)]
        assert long_history.main(args) == 0
    result = json.loads(out.read_text())
    row = result["per_question"][0]
    assert set(row["search"]) == {"base", "rerank"}  # --system1 adds the rerank variant
    assert row["search"]["rerank"]["none"]["budgets"]["1000"]["all"] is True
    assert row["system1"]["scored"] > 0
    assert result["meta"]["rerank"] == {"system1": base, "system1_kind": "noul", "candidates": 10,
                                        "rerank_context": "own", "rerank_fusion": "replace"}
    assert json.loads(log.read_text().splitlines()[0])["settings"]["rerank"]["system1_kind"] == "noul"


def test_cached_ranker_sends_a_long_list_in_chunks():
    from cogito_mem import system1

    class Sizes(_Counting):
        def __init__(self):
            super().__init__()
            self.calls: list[int] = []

        def score(self, query, texts):
            self.calls.append(len(texts))
            return super().score(query, texts)

    inner = Sizes()
    texts = [f"message {i}" for i in range(system1.POINTWISE_CHUNK * 2 + 5)] + ["Biscuit"]
    scores = CachedRanker(inner, ScoreCache(None)).score("q", texts)
    assert inner.calls == [system1.POINTWISE_CHUNK, system1.POINTWISE_CHUNK, 6]
    assert scores[-1] == 0.9 and len(scores) == len(texts)
