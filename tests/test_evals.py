"""The stage-0 tools on a small dataset shaped like LongMemEval (pipeline checks)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from cogito_mem.evals import longmemeval, speed
from cogito_mem.evals.common import parse_count, quantization


def mini_longmemeval() -> list[dict]:
    filler = [
        [{"role": "user", "content": "What is a good stretch for back pain?"},
         {"role": "assistant", "content": "Try the cat-cow stretch, slowly, ten times."}],
        [{"role": "user", "content": "Recommend a sci-fi novel."},
         {"role": "assistant", "content": "Try The Left Hand of Darkness by Ursula K. Le Guin."}],
        [{"role": "user", "content": "How do I descale a kettle?"},
         {"role": "assistant", "content": "Boil a mix of water and vinegar, then rinse twice."}],
    ]  # fmt: skip
    evidence_a = [
        {"role": "user", "content": "I just adopted a beagle and named him Biscuit.", "has_answer": True},
        {"role": "assistant", "content": "Congratulations on adopting Biscuit!"},
    ]
    long_answer = "\n\n".join(
        f"Part {i}. " + " ".join(f"The itinerary detail {i}.{j} is noted." for j in range(25)) for i in range(4)
    ) + "\n\nThe hotel in Lisbon is called Casa Azul."
    evidence_b = [
        {"role": "user", "content": "Plan my trip to Lisbon."},
        {"role": "assistant", "content": long_answer, "has_answer": True},
    ]

    def q(qid, question, sessions, dates, answer_ids, qtype):
        return {
            "question_id": qid,
            "question_type": qtype,
            "question": question,
            "answer": "x",
            "question_date": "2023/06/01 (Thu) 10:00",
            "haystack_session_ids": [f"{qid}-s{i}" for i in range(len(sessions))],
            "haystack_dates": dates,
            "haystack_sessions": sessions,
            "answer_session_ids": answer_ids,
        }

    dates = ["2023/05/03 (Wed) 09:00", "2023/05/01 (Mon) 09:00", "2023/05/02 (Tue) 09:00", "2023/05/04 (Thu) 09:00"]
    return [
        q("q1", "What did I name my dog?", filler + [evidence_a], dates, ["q1-s3"], "single-session-user"),
        q("q2", "What is the name of the hotel in Lisbon?", [evidence_b] + filler, dates, ["q2-s0"], "single-session-assistant"),
        q("q3_abs", "What is my cat called?", filler + [evidence_a], dates, [], "single-session-user"),
    ]  # fmt: skip


@pytest.fixture
def data(tmp_path) -> Path:
    path = tmp_path / "longmemeval_mini.json"
    path.write_text(json.dumps(mini_longmemeval()))
    return path


def run(tmp_path, data, arm: str, *extra: str) -> dict:
    out = tmp_path / f"{arm}.json"
    argv = ["run", "--data", str(data), "--arm", arm, "--embedder", "hash",
            "--cache", str(tmp_path / "cache.sqlite3"), "--out", str(out), *extra]  # fmt: skip
    assert longmemeval.main(argv) == 0
    return json.loads(out.read_text())


def test_longmemeval_run_reports_coverage_and_recall(tmp_path, data):
    result = run(tmp_path, data, "U2", "--build-check", "0.5,0.6")
    s = result["summary"]
    assert s["questions"] == 2  # the _abs question is left out
    assert set(s["coverage"]) == {"100", "300", "1000"}
    assert s["coverage"]["1000"] == 1.0 and s["recall_all@10"] == 1.0
    assert s["evidence_turns"] == 2 and s["evidence_split_share"] == 0.5  # the long answer was split
    assert s["build_check"]["ok"] is True
    assert set(s["coverage_300_by_type"]) == {"single-session-user", "single-session-assistant"}
    meta = result["meta"]
    for key in ("dataset_sha256", "model", "commit", "machine", "started_utc", "finished_utc", "config"):
        assert meta[key] is not None, key
    assert meta["model"] == "hash-v1" and meta["config"]["search"] == "hybrid"
    rows = {r["question_id"]: r for r in result["per_question"]}
    assert rows["q1"]["covered"] == {"100": True, "300": True, "1000": True}
    assert all(r["tokens"]["100"] <= 100 for r in rows.values())


def test_longmemeval_arms_and_compare(tmp_path, data, capsys):
    u1 = run(tmp_path, data, "U1")
    u3 = run(tmp_path, data, "U3", "--base", "U1")
    assert u1["meta"]["config"] == {"search": "vector", "doc_context": "own", "doc_author": False, "candidates": 30}
    assert u3["meta"]["config"]["doc_context"] == "previous"
    capsys.readouterr()
    assert longmemeval.main(["compare", str(tmp_path / "U1.json"), str(tmp_path / "U3.json"), "--bootstrap", "200"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["questions"] == 2 and len(out["ci95_points"]) == 2 and "counts" in out


def test_paired_bootstrap():
    mean, lo, hi = longmemeval.paired_bootstrap([0, 0, 0, 0], [1, 1, 1, 1], n_boot=100)
    assert mean == lo == hi == 1.0
    mean, lo, hi = longmemeval.paired_bootstrap([0, 1] * 50, [1, 1] * 50, n_boot=500)
    assert mean == 0.5 and lo < 0.5 < hi


def test_dates_and_helpers():
    assert longmemeval.parse_date("2023/05/20 (Sat) 02:21") == longmemeval.timeutil.parse("2023-05-20T02:21:00Z")
    assert parse_count("10M") == 10_000_000 and parse_count("1.5k") == 1500 and parse_count("512") == 512
    assert quantization("embeddinggemma-2-Q8_0.gguf") == "Q8_0"
    assert quantization("embeddinggemma-2-BF16.gguf") == "BF16"
    assert quantization("hash-v1") is None


def test_speed_bench_runs(tmp_path, capsys):
    out = tmp_path / "speed.json"
    argv = ["speed", "--embedder", "hash", "--tokens", "30k", "--queries", "60", "--http", "10",
            "--append-sizes", "512,1k", "--append-reps", "2", "--cache", str(tmp_path / "c.sqlite3"),
            "--out", str(out)]  # fmt: skip
    assert speed.main(argv) == 0
    res = json.loads(out.read_text())["results"]
    assert res["memory"]["tokens"] >= 30_000
    assert res["query_in_process"]["n"] == 60
    assert set(res["query_in_process"]) >= {"median_ms", "p95_ms", "max_ms"}
    assert res["query_http_round_trip"]["n"] == 10
    assert set(res["append_call"]) == {"512", "1000"}
    assert res["time_to_searchable_by_meaning"]["n"] == 2
    assert isinstance(res["gate_passed"], bool)


def test_speed_bench_with_random_vectors_and_lme_data(tmp_path, data):
    out = tmp_path / "speed.json"
    argv = ["speed", "--data", str(data), "--embedder", "hash", "--tokens", "1k", "--queries", "20", "--http", "0",
            "--append-sizes", "", "--random-vectors", "--cache", str(tmp_path / "c.sqlite3"), "--out", str(out)]  # fmt: skip
    assert speed.main(argv) == 0
    result = json.loads(out.read_text())
    assert result["meta"]["sessions_used"]  # the sessions used are recorded
    assert result["results"]["memory"]["random_vectors"] is True


def mini_locomo() -> list[dict]:
    conv = {
        "speaker_a": "Ana", "speaker_b": "Ben",
        "session_1_date_time": "1:56 pm on 8 May, 2023",
        "session_1": [
            {"speaker": "Ana", "dia_id": "D1:1", "text": "I adopted a beagle called Biscuit last week!"},
            {"speaker": "Ben", "dia_id": "D1:2", "text": "That's lovely. I started pottery classes."},
        ],
        "session_2_date_time": "10:00 am on 20 May, 2023",
        "session_2": [
            {"speaker": "Ana", "dia_id": "D2:1", "text": "Biscuit loves the beach.", "blip_caption": "a photo of a dog on sand"},
            {"speaker": "Ben", "dia_id": "D2:2", "text": "My pottery teacher is from Kyoto."},
        ] + [{"speaker": "Ana", "dia_id": f"D2:{i}", "text": f"Filler chat number {i} about the weather."} for i in range(3, 40)],
    }  # fmt: skip
    qa = [
        {"question": "What is the name of Ana's dog?", "evidence": ["D1:1"], "category": 4, "answer": "Biscuit"},
        {"question": "Where is Ben's pottery teacher from?", "evidence": ["D2:2"], "category": 4, "answer": "Kyoto"},
        {"question": "Where does Ana's dog like to go?", "evidence": ["D1:1; D2:1"], "category": 1, "answer": "beach"},
        {"question": "What is Ben's favourite colour?", "category": 5, "adversarial_answer": "blue"},
    ]
    return [{"sample_id": "mini-1", "conversation": conv, "qa": qa}]


def test_locomo_run(tmp_path, capsys):
    from cogito_mem.evals import locomo

    data = tmp_path / "locomo.json"
    data.write_text(json.dumps(mini_locomo()))
    out = tmp_path / "locomo-out.json"
    argv = ["--data", str(data), "--search", "hybrid", "--embedder", "hash", "--cache", str(tmp_path / "c.sqlite3"),
            "--out", str(out)]  # fmt: skip
    assert locomo.main(argv) == 0
    result = json.loads(out.read_text())
    s = result["summary"]
    assert s["questions"] == 3  # the adversarial question is left out
    assert s["coverage"]["1000"] == 1.0
    assert s["baseline_recent"]["100"] == 0.0  # the answers are not in the last 100 tokens
    assert set(s["by_category@300"]) == {"single-hop", "multi-hop"}
    assert locomo.evidence_ids(["D1:1; D2:1", "D:11:26", "D"]) == ["D1:1", "D2:1", "D11:26"]
    assert locomo.parse_when("1:56 pm on 8 May, 2023") == longmemeval.timeutil.parse("2023-05-08T13:56:00Z")
    capsys.readouterr()
    assert locomo.main(["compare", str(out), str(out), "--bootstrap", "100"]) == 0
    assert json.loads(capsys.readouterr().out)["difference_points"] == 0.0


class _FakeChat(BaseHTTPRequestHandler):
    """An OpenAI-compatible endpoint: always answers "Biscuit"; the judge says CORRECT when the gold is Biscuit."""

    calls = 0

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls += 1
        prompt = body["messages"][-1]["content"]
        if body.get("response_format"):
            content = json.dumps({"label": "CORRECT" if "Gold answer: Biscuit" in prompt else "WRONG"})
        else:
            content = "Biscuit"
        data = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.001}}).encode()  # fmt: skip
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.mark.parametrize("protocol", ["mem0-2025", "mem0-2026"])
@pytest.mark.parametrize("context", ["memory", "full"])
def test_locomo_qa_run_and_cache(tmp_path, capsys, protocol, context):
    from cogito_mem.evals import locomo_qa

    srv = HTTPServer(("127.0.0.1", 0), _FakeChat)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _FakeChat.calls = 0
    try:
        data = tmp_path / "locomo.json"
        data.write_text(json.dumps(mini_locomo()))
        env = tmp_path / ".env"
        env.write_text("OPENROUTER_AUTH_TOKEN: test-key\n")
        out = tmp_path / "qa.json"
        argv = ["--data", str(data), "--protocol", protocol, "--context", context, "--embedder", "hash",
                "--cache", str(tmp_path / "c.sqlite3"), "--llm-cache", str(tmp_path / "llm.jsonl"),
                "--env-file", str(env), "--base-url", f"http://127.0.0.1:{srv.server_address[1]}", "--out", str(out)]  # fmt: skip
        assert locomo_qa.main(argv) == 0
        s = json.loads(out.read_text())["summary"]
        assert s["questions"] == 3 and s["J"] == pytest.approx(100 / 3, abs=0.01)  # the adversarial one is left out
        assert s["by_category"]["single-hop"]["n"] == 2 and s["llm_cost_usd"] == pytest.approx(0.006)
        if context == "memory":
            assert s["evidence_covered"] > 0 and "retrieve_ms" in s
        assert _FakeChat.calls == 6
        assert locomo_qa.main(argv) == 0  # a rerun is answered from the cache
        assert _FakeChat.calls == 6
        capsys.readouterr()
        assert locomo_qa.main(["compare", str(out), str(out), "--bootstrap", "100"]) == 0
        assert json.loads(capsys.readouterr().out)["difference_points"] == 0.0
    finally:
        srv.shutdown()


def test_locomo_qa_helpers(tmp_path):
    from cogito_mem.evals import locomo_qa

    assert locomo_qa.when_text("2023-05-08T13:56:00.003Z") == "1:56 pm on 8 May, 2023"
    bare = locomo_qa.without_captions(mini_locomo()[0])
    assert "blip_caption" not in bare["conversation"]["session_2"][0] and "blip_caption" in mini_locomo()[0]["conversation"]["session_2"][0]
    assert [t for _, _, t in locomo_qa.full_lines(bare)][2] == "Biscuit loves the beach."
    assert locomo_qa.when_text("2023-05-08T00:05:00Z") == "12:05 am on 8 May, 2023"
    assert locomo_qa.token_f1("Biscuit, the beagle.", "biscuit") == pytest.approx(0.5)
    assert locomo_qa.judge_label('{"label": "CORRECT"}') == (True, True)
    assert locomo_qa.judge_label('Reasoning... so: WRONG') == (False, False)
    assert locomo_qa.extract_answer("mem0-2026", "Step 1 ... ANSWER: Kyoto") == "Kyoto"
    env = tmp_path / ".env"
    env.write_text("# keys\nA_KEY: one\nexport B_KEY='two'\nC_KEY=three\n")
    assert locomo_qa.read_env_file(env) == {"A_KEY": "one", "B_KEY": "two", "C_KEY": "three"}
