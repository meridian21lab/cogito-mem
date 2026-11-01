"""The stage-0 tools on a small dataset shaped like LongMemEval (pipeline checks)."""

from __future__ import annotations

import argparse
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


def test_query_past_top_k_limit(tmp_path):
    from cogito_mem.api import MAX_TOP_K
    from cogito_mem.errors import ApiError
    from cogito_mem.evals.common import query_past_top_k_limit
    from cogito_mem.memory import Config, Memory

    n = MAX_TOP_K + 20
    items = [{"author": "ana", "text": f"note {i} about the beach"} for i in range(n)]
    with Memory(None, config=Config(search="keyword")) as mem:
        for i in range(0, n, 500):
            mem.append(items[i : i + 500], namespace="c")
        body = {"op": "query", "namespace": "c", "text": "beach", "top_k": n, "max_tokens": 50000}
        assert len(query_past_top_k_limit(mem, body)["items"]) == n
        with pytest.raises(ApiError):
            mem.handle(body)  # the API itself keeps its limit


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
    assert set(s["coverage"]) == {"100", "300", "1000", "2500", "5000"}
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
    bodies: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls += 1
        type(self).bodies.append(body)
        prompt = body["messages"][-1]["content"]
        if isinstance(prompt, list):  # a cacheable prefix and the question, as parts
            prompt = "".join(part["text"] for part in prompt)
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


def test_locomo_qa_memory_limit_keeps_the_best_ranked(monkeypatch):
    from cogito_mem.evals import locomo_qa
    from cogito_mem.memory import Config, Memory

    def ask(protocol):
        args = argparse.Namespace(context="memory", protocol=protocol, top_k=100, budget=5000)
        with Memory(None, config=Config(search="keyword")) as mem:
            _, rows = locomo_qa.retrieve(mem, mini_locomo()[0], args)
        return rows[0]["items"]

    everything = ask("mem0-2025")
    assert len(everything) > 1
    monkeypatch.setattr(locomo_qa, "BENCH_MEMORY_LIMIT", 1)
    assert len(ask("mem0-2025")) == len(everything)  # the limit belongs to the 2026 protocol
    assert len(ask("mem0-2026")) == 1


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


def test_locomo_qa_reasoning_models_and_two_judges(tmp_path):
    from cogito_mem.evals import locomo_qa

    _FakeChat.bodies = []
    srv = HTTPServer(("127.0.0.1", 0), _FakeChat)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        data = tmp_path / "locomo.json"
        data.write_text(json.dumps(mini_locomo()))
        env = tmp_path / ".env"
        env.write_text("OPENROUTER_API_KEY=test-key\n")
        out = tmp_path / "qa.json"
        argv = ["--data", str(data), "--protocol", "mem0-2026", "--context", "full", "--answer-model", "anthropic/claude-haiku-5.5",
                "--judge-model", "openai/gpt-5-mini", "--judge-reasoning", "minimal", "--judge-max-tokens", "500",
                "--judges", "mem0-2026,mem0-2025", "--answer-provider", "GMICloud,Parasail", "--llm-cache", str(tmp_path / "llm.jsonl"), "--env-file", str(env),
                "--base-url", f"http://127.0.0.1:{srv.server_address[1]}", "--out", str(out)]  # fmt: skip
        assert locomo_qa.main(argv) == 0
        result = json.loads(out.read_text())
        s = result["summary"]
        assert set(s["J_by_judge"]) == {"mem0-2026", "mem0-2025"} and s["empty_answers"] == 0
        assert result["meta"]["judges"] == ["mem0-2026", "mem0-2025"] and result["meta"]["served_by"]
        assert all(set(r["judgments"]) == {"mem0-2026", "mem0-2025"} for r in result["per_question"])
        answers = [b for b in _FakeChat.bodies if not b.get("response_format")]
        judges = [b for b in _FakeChat.bodies if b.get("response_format")]
        assert all(b["temperature"] == 0.0 and b["messages"][0]["content"][0]["cache_control"] for b in answers)
        assert all(b["provider"] == {"order": ["GMICloud", "Parasail"], "allow_fallbacks": False} for b in answers)
        assert all(b["reasoning"] == {"effort": "minimal"} and b["max_tokens"] == 500 and "temperature" not in b for b in judges)
    finally:
        srv.shutdown()
    msgs = locomo_qa.answer_messages("mem0-2026", "full", "Where?", mini_locomo()[0], [], cache=True)
    parts = msgs[0]["content"]
    assert parts[0]["cache_control"] == {"type": "ephemeral"} and parts[1]["text"].startswith("\n\nQuestion: Where?")
    assert locomo_qa.answer_messages("mem0-2026", "full", "Where?", mini_locomo()[0], [])[0]["content"] == parts[0]["text"] + parts[1]["text"]


class _DropsFirstBody(BaseHTTPRequestHandler):
    """The first answer stops in the middle of its chunked body, as a host that drops the connection does."""

    calls = 0

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers["Content-Length"]))
        type(self).calls += 1
        self.send_response(200)
        if type(self).calls == 1:
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(b"10\r\n{\"choices\": [")
            self.wfile.flush()
            self.close_connection = True
            return
        data = json.dumps({"choices": [{"message": {"content": "Biscuit"}, "finish_reason": "stop"}], "usage": {}}).encode()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_locomo_qa_llm_retries_a_dropped_body():
    from cogito_mem.evals import locomo_qa

    srv = HTTPServer(("127.0.0.1", 0), _DropsFirstBody)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        llm = locomo_qa.LLM(f"http://127.0.0.1:{srv.server_address[1]}", "key", None, retry_delay=0.01)
        assert llm.chat("m", [{"role": "user", "content": "hi"}])["content"] == "Biscuit"
        assert _DropsFirstBody.calls == 2
    finally:
        srv.shutdown()


def lme_question(chars: int) -> dict:
    return {"haystack_sessions": [[{"role": "user", "content": "x" * chars}], [{"role": "assistant", "content": "y" * chars}]]}


def test_full_context_sizes():
    from cogito_mem.evals import full_context as fc

    tokens = [fc.history_chars(lme_question(n)) // fc.CHARS_PER_TOKEN for n in (1_000_000, 3_000_000)]
    assert tokens == [500_000, 1_500_000]
    s = fc.summarize_sizes(tokens)
    assert s["share_over"]["1000000"] == 0.5 and s["share_over"]["200000"] == 1.0
    assert s["tokens"]["max"] == 1_500_000


def test_full_context_history_text_is_real_turns_cut_to_size():
    from cogito_mem.evals import full_context as fc

    text = fc.history_text([lme_question(50), lme_question(50)], 150)
    assert len(text) == 150 and text.startswith("user: xxx") and "assistant: yyy" in text
    with pytest.raises(ValueError):
        fc.history_text([lme_question(5)], 1000)


def test_full_context_probe_stops_at_first_acceptance_and_at_max_cost():
    from cogito_mem.evals import full_context as fc

    def fake(model, text):
        if len(text) > 100:
            return {"accepted": False, "status": 400, "error": "too long"}
        return {"accepted": True, "cost_usd": 1.0}

    rows, spent = fc.probe(["a", "b"], (50, 200, 500), lambda n: "x" * n, fake, max_cost=10)
    assert [(r["model"], r["sent_tokens_approx"], r["accepted"]) for r in rows] == [
        ("a", 500, False), ("a", 200, False), ("a", 50, True), ("b", 500, False), ("b", 200, False), ("b", 50, True)]  # fmt: skip
    assert spent == 2.0
    rows, spent = fc.probe(["a", "b"], (50,), lambda n: "x" * n, fake, max_cost=1)
    assert spent == 1.0 and rows[-1] == {"model": "b", "sent_tokens_approx": 50, "skipped": "max cost reached"}


def test_full_context_send_reports_a_refusal_as_a_result():
    from cogito_mem.evals import full_context as fc

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["transforms"] == []  # nothing may be silently compressed
            too_long = len(body["messages"][0]["content"]) > 200
            reply = ({"error": {"code": 400, "message": "Provider returned error", "metadata": {"raw": "prompt is too long"}}}
                     if too_long else
                     {"choices": [{"message": {"content": "OK"}}], "provider": "p", "usage": {"prompt_tokens": 42, "cost": 0.5}})  # fmt: skip
            self.send_response(400 if too_long else 200)
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        no = fc.send(base, "k", "m", "x" * 500, 10, 5)
        assert no["accepted"] is False and no["status"] == 400 and no["error"] == "prompt is too long"
        yes = fc.send(base, "k", "m", "x", 10, 5)
        assert yes["accepted"] is True and yes["billed_prompt_tokens"] == 42 and yes["cost_usd"] == 0.5
    finally:
        server.shutdown()


def test_full_context_sessions_count_tokens_and_forks_once(tmp_path, capsys):
    from cogito_mem.evals import full_context as fc

    project = tmp_path / "p"
    project.mkdir()

    def write(name, boundaries, context):
        lines = [{"type": "system", "subtype": "compact_boundary", "uuid": u, "compactMetadata": {"preTokens": t}, "content": "secret"}
                 for u, t in boundaries]  # fmt: skip
        lines.append({"type": "assistant", "message": {"content": "secret", "usage": {"input_tokens": 1, "cache_read_input_tokens": context}}})
        (project / name).write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")

    write("a.jsonl", [("u1", 900_000), ("u2", 800_000)], 100)
    write("fork.jsonl", [("u1", 900_000)], 5000)
    assert fc.main(["sessions", "--root", str(tmp_path)]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["sessions"] == 2 and s["compactions"] == 2 and s["sessions_history_over_1M"] == 1
    assert s["largest_history"] == 1_700_101
    assert "secret" not in json.dumps(s)


def long_history_question(qid="q1", sessions=8):
    ids = [f"s{i}" for i in range(sessions)]
    turns = [[{"role": "user", "content": f"session {i} is about topic number {i} and its garden"},
              {"role": "assistant", "content": f"noted topic {i}"}] for i in range(sessions)]
    turns[3] = [{"role": "user", "content": "My passport number ends in 4411 and the kiwi plant died.", "has_answer": True},
                {"role": "assistant", "content": "Sorry about the kiwi plant."}]
    return {"question_id": qid, "question_type": "single-session-user", "question": "What plant of mine died recently?",
            "question_date": "2023/06/01 (Thu) 10:00", "answer": "the kiwi plant", "answer_session_ids": ["s3"],
            "haystack_session_ids": ids, "haystack_dates": [f"2023/05/{i % 28 + 1:02d} (Mon) 09:{i % 60:02d}" for i in range(sessions)],
            "haystack_sessions": turns}


def test_long_history_measures_search_delivery_and_recency(tmp_path):
    from cogito_mem.evals import long_history

    data = tmp_path / "m.json"
    data.write_text(json.dumps([long_history_question(sessions=60), long_history_question("q2_abs", sessions=60)]))
    out = tmp_path / "r.json"
    contexts = tmp_path / "c.jsonl"
    code = long_history.main(["run", "--data", str(data), "--embedder", "hash", "--variants", "base,exact,session",
                              "--cache", str(tmp_path / "e.sqlite3"), "--contexts-out", str(contexts), "--out", str(out)])
    assert code == 0
    result = json.loads(out.read_text())
    row = result["per_question"][0]
    assert row["evidence_turns"] == 1
    assert row["search"]["base"]["none"]["session"]["recall_any@1"] is True
    assert row["search"]["base"]["question"]["budgets"]["1000"]["all"] is True
    assert set(row["delivery"]) == {"shipped", "pointers"}
    assert row["recency"]["300"]["none"]["all"] is False  # session 3 of 60 is not in the last 300 tokens
    assert result["summary"]["answerable_with_labels"] == 1
    arms = json.loads(contexts.read_text().splitlines()[0])["arms"]
    assert "kiwi" in " ".join(a["text"] for a in arms["oracle"]) and arms["search-1000"]


def test_long_history_subset_keeps_the_evidence():
    from cogito_mem.evals import long_history

    q = long_history_question(sessions=40)
    small = long_history.subset(q, 5, seed=1)
    assert len(small["haystack_session_ids"]) == 5 and "s3" in small["haystack_session_ids"]
    assert small == long_history.subset(q, 5, seed=1)
    assert long_history.subset(q, 100) is q


def test_long_history_splits_are_stable():
    from cogito_mem.evals.long_history import split_of

    assert {split_of(f"q{i}") for i in range(100)} == {"tuning", "heldout"}
    assert split_of("q1") == split_of("q1")


def test_identifier_lane_finds_a_token_word_for_word():
    from cogito_mem.memory import Config, Memory
    from cogito_mem.terms import identifiers

    assert identifiers("look at src/app/run.py and --top-k 5bba30a please, GPT-5.") >= {"src/app/run.py", "--top-k", "5bba30a", "gpt-5"}
    assert not identifiers("just some plain words here")
    items = [{"author": "ana", "text": f"run {i} of job-{i:04d} finished without trouble"} for i in range(300)]
    with Memory(None, embedder="hash", config=Config(search="keyword", exact_lane=True)) as mem:
        mem.append(items, namespace="c")
        top = mem.query("what happened with job-0137 finished", namespace="c", top_k=3)["items"]
    assert "job-0137" in top[0]["text"]
