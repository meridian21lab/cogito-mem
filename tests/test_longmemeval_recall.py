"""`eval longmemeval-recall` on a small dataset shaped like LongMemEval-S, with hand-checked rankings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cogito_mem.evals import longmemeval_recall
from cogito_mem.evals.longmemeval_recall import distinct, score

BOOK_FILLERS = [
    ("Can you suggest a book about gardening?", "Try The Well-Tempered Garden by Christopher Lloyd."),
    ("Is there a good book on sourdough baking?", "Flour Water Salt Yeast is a classic."),
    ("Which book explains black holes simply?", "A Brief History of Time is a good start."),
    ("I need a book for learning Spanish.", "Madrigal's Magic Key to Spanish works well."),
    ("Suggest a book about the history of Rome.", "SPQR by Mary Beard is excellent."),
    ("Any book on chess openings for beginners?", "Start with Logical Chess, Move by Move."),
    ("I want a book about birdwatching.", "The Sibley Guide to Birds is the standard."),
    ("What is a good book on personal finance?", "The Psychology of Money is popular."),
    ("Find me a book about woodworking.", "The Joint Book is a solid reference."),
    ("Is there a book about mountain climbing?", "Into Thin Air by Jon Krakauer."),
]  # fmt: skip

LOG2_3 = 1.5849625007211562  # log2(3): the discount at rank 2
LOG2_5 = 2.321928094887362  # log2(5): the discount at rank 4


def turns(user: str, assistant: str, answer: str | None = None) -> list[dict]:
    return [{"role": "user", "content": user, "has_answer": answer == "user"},
            {"role": "assistant", "content": assistant, "has_answer": answer == "assistant"}]  # fmt: skip


def mini_longmemeval_s() -> list[dict]:
    """Ten filler sessions that all say "book", plus each question's own sessions.

    Hand-checked for hybrid search: each question's first evidence session holds the only
    turn that shares a rare word with the question, so it ranks first. q2's second evidence
    session shares no word with the question: it is found by its vector alone, below the 11
    sessions whose user turn matches a word of the question in both lists (reciprocal rank
    fusion: 1/(60+a) + 1/(60+b) > 1/61 while there are fewer than 62 items), so 12th or lower.
    q4's best match is dated after the question and must stay invisible (``as_of``).
    """
    fillers = [(f"filler_{i}", f"2023/05/{i + 1:02d} (Mon) 09:00", turns(u, a)) for i, (u, a) in enumerate(BOOK_FILLERS)]

    def q(qid, qtype, question, own, answer_ids):
        sessions = fillers + own
        return {
            "question_id": qid, "question_type": qtype, "question": question, "answer": "x",
            "question_date": "2023/06/01 (Thu) 10:00",
            "haystack_session_ids": [s[0] for s in sessions], "haystack_dates": [s[1] for s in sessions],
            "haystack_sessions": [s[2] for s in sessions], "answer_session_ids": answer_ids,
        }  # fmt: skip

    beagle = ("answer_q1", "2023/05/15 (Mon) 18:00",
              turns("I just adopted a beagle and named him Biscuit.", "Congratulations on adopting Biscuit!", "user"))
    no_cat = (beagle[0], beagle[1], turns(beagle[2][0]["content"], beagle[2][1]["content"]))
    hotel = ("answer_q2_a", "2023/05/16 (Tue) 08:00",
             turns("I booked a room at the Casa Azul hotel for my Lisbon trip.", "Casa Azul has a lovely rooftop.", "user"))
    sister = ("answer_q2_b", "2023/05/20 (Sat) 12:00",
              turns("My sister flew in from Porto yesterday.", "Lovely, enjoy the time together.", "user"))
    yoga = ("answer_q3", "2023/05/18 (Thu) 07:30",
            turns("I want to start going to classes.", "I recommend the Lotus yoga studio on Main Street.", "assistant"))
    marathon = ("answer_q4", "2023/05/10 (Wed) 20:00",
                turns("I ran the Boston marathon last Sunday!", "Well done, that is a big achievement.", "user"))
    later = ("later_q4", "2023/07/01 (Sat) 09:00",
             turns("I will run the Boston marathon again, when did I run it first?", "Good luck with the training."))
    return [
        q("q1", "single-session-user", "What name did I give my new beagle?", [beagle], ["answer_q1"]),
        q("q2", "multi-session", "Which hotel did I book for the Lisbon trip?", [hotel, sister], ["answer_q2_a", "answer_q2_b"]),
        q("q3", "single-session-assistant", "Which yoga studio did you recommend?", [yoga], ["answer_q3"]),
        q("q4", "temporal-reasoning", "When did I run the Boston marathon?", [marathon, later], ["answer_q4"]),
        q("q5_abs", "single-session-user", "What did I name my cat?", [no_cat], ["answer_q1"]),
    ]  # fmt: skip


@pytest.fixture
def data(tmp_path) -> Path:
    path = tmp_path / "longmemeval_s_mini.json"
    path.write_text(json.dumps(mini_longmemeval_s()))
    return path


def run(tmp_path, data, search: str, *extra: str) -> dict:
    out = tmp_path / f"recall-{search}.json"
    argv = ["--data", str(data), "--search", search, "--embedder", "hash", "--cache", str(tmp_path / "cache.sqlite3"),
            "--out", str(out), *extra]  # fmt: skip
    assert longmemeval_recall.main(argv) == 0
    return json.loads(out.read_text())


def test_score_a_ranking():
    s = score(["s4", "s1", "s2", "s3", "s0"], {"s1", "s3"})
    assert s["rank"] == 2
    assert [s[f"recall_any@{k}"] for k in (1, 3, 5, 10)] == [False, True, True, True]
    assert [s[f"recall_all@{k}"] for k in (1, 3, 5, 10)] == [False, False, True, True]
    assert s["ndcg@10"] == pytest.approx((1 / LOG2_3 + 1 / LOG2_5) / (1 + 1 / LOG2_3), abs=1e-4)
    miss = score(["s4", "s0"], {"s1"})
    assert miss["rank"] is None and not miss["recall_any@10"] and miss["ndcg@10"] == 0.0
    assert score(["s1"], {"s1"})["ndcg@10"] == 1.0
    assert score([f"s{i}" for i in range(12)], {"s11"})["recall_any@10"] is False
    assert distinct(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_run_hybrid(tmp_path, data, capsys):
    result = run(tmp_path, data, "hybrid")
    rows = {r["question_id"]: r for r in result["per_question"]}
    q1, q2, q3, q4, q5 = (rows[q] for q in ("q1", "q2", "q3", "q4", "q5_abs"))
    assert q1["session"]["rank"] == 1 and q1["turn"]["rank"] == 1 and q1["session"]["ndcg@10"] == 1.0
    # q2: the hotel session first, the sister's session below the ten "book" fillers
    assert q2["evidence_sessions"] == 2 and q2["evidence_turns"] == 2
    assert q2["session"]["rank"] == 1 and q2["session"]["recall_any@1"] and not q2["session"]["recall_all@10"]
    assert q2["ranked_sessions"].index("answer_q2_b") >= 11
    assert q2["session"]["ndcg@10"] == pytest.approx(1 / (1 + 1 / LOG2_3), abs=1e-4)
    assert q2["turn"]["rank"] == 1 and not q2["turn"]["recall_all@10"]
    # q3: the evidence is the assistant's turn
    assert q3["session"]["rank"] == 1 and q3["evidence_turns"] == 1 and q3["turn"]["recall_any@3"]
    # q4: the session dated after the question is not visible as of the question date
    assert q4["session"]["rank"] == 1 and "later_q4" not in q4["ranked_sessions"]
    assert q4["sessions"] == 12 and q4["sessions_ranked"] == 11
    assert q5["abstention"] and q5["session"] is not None and q5["turn"] is None  # it has no has_answer turn
    s = result["summary"]
    assert s["questions"] == 5 and s["skipped_no_evidence"] == 0 and s["evidence_sessions_missing"] == 0
    assert (s["all"]["session"]["n"], s["answerable"]["session"]["n"], s["abstention"]["session"]["n"]) == (5, 4, 1)
    ans = s["answerable"]["session"]
    assert ans["recall_any@1"] == 1.0 and ans["recall_all@10"] == 0.75 and ans["mrr"] == 1.0
    assert ans["ndcg@10"] == pytest.approx((3 + 1 / (1 + 1 / LOG2_3)) / 4, abs=1e-4)
    assert s["answerable"]["turn"]["n"] == 4 and s["all"]["turn"]["n"] == 4 and s["abstention"]["turn"] == {"n": 0}
    assert list(s["by_type"]) == ["single-session-user", "single-session-assistant", "multi-session", "temporal-reasoning"]
    assert s["by_type"]["multi-session"]["session"]["recall_all@5"] == 0.0
    assert s["fewer_than_10_sessions_ranked"] == 0
    meta = result["meta"]
    assert meta["model"] == "hash-v1" and meta["config"]["search"] == "hybrid" and meta["wall_s"] >= 0
    assert meta["dataset_sha256"] and meta["top_k"] == 100 and meta["resumed_questions"] == 0
    table = capsys.readouterr().out
    assert "answerable (no _abs)" in table and "  multi-session" in table and "R@5" in table


def test_resume_keyword_and_compare(tmp_path, data, capsys):
    log = tmp_path / "questions.jsonl"
    hybrid = run(tmp_path, data, "hybrid", "--questions-out", str(log))
    assert len(log.read_text().splitlines()) == 6  # the settings, then one line per question
    with open(log, "a") as fh:
        fh.write('{"question_id": "q9", "cut sh')  # an interrupted write is ignored
    again = run(tmp_path, data, "hybrid", "--questions-out", str(log))
    assert again["meta"]["resumed_questions"] == 5 and again["summary"] == hybrid["summary"]
    capsys.readouterr()
    argv = ["--data", str(data), "--search", "keyword", "--cache", str(tmp_path / "c.sqlite3"), "--questions-out", str(log)]
    assert longmemeval_recall.main(argv) == 2  # a log written with other settings is not mixed in
    assert "other settings" in capsys.readouterr().err

    keyword = run(tmp_path, data, "keyword")
    rows = {r["question_id"]: r for r in keyword["per_question"]}
    assert keyword["meta"]["model"] is None
    assert "answer_q2_b" not in rows["q2"]["ranked_sessions"]  # no word in common: BM25 never finds it
    assert rows["q5_abs"]["items_returned"] == 0 and rows["q5_abs"]["session"]["rank"] is None
    assert rows["q2"]["sessions_ranked"] == 11  # the hotel session and the ten that say "book"
    assert keyword["summary"]["fewer_than_10_sessions_ranked"] == 4
    capsys.readouterr()
    a, b = tmp_path / "recall-keyword.json", tmp_path / "recall-hybrid.json"
    assert longmemeval_recall.main(["compare", str(a), str(b), "--bootstrap", "200"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["set"] == "all" and out["a"]["search"] == "keyword" and out["b"]["search"] == "hybrid"
    r5 = out["metrics"]["session_recall_any@5"]
    assert r5["questions"] == 5 and len(r5["ci95_points"]) == 2
    assert r5["difference_points"] == pytest.approx(100 * (r5["b"] - r5["a"]), abs=0.01)
    argv = ["compare", str(b), str(b), "--set", "answerable", "--metrics", "turn_recall_all@10,session_mrr", "--bootstrap", "50"]
    assert longmemeval_recall.main(argv) == 0
    out = json.loads(capsys.readouterr().out)["metrics"]
    assert out["turn_recall_all@10"]["questions"] == 4 and out["turn_recall_all@10"]["difference_points"] == 0.0
    assert out["session_mrr"] == {"questions": 0}  # MRR is a summary, not a per-question score


def test_from_the_cli(tmp_path, data, capsys):
    from cogito_mem.cli import main

    out = tmp_path / "cli.json"
    argv = ["eval", "longmemeval-recall", "--data", str(data), "--search", "keyword", "--limit", "2",
            "--cache", str(tmp_path / "c.sqlite3"), "--out", str(out)]  # fmt: skip
    assert main(argv) == 0
    assert json.loads(out.read_text())["summary"]["questions"] == 2
    assert "session level" in capsys.readouterr().out
