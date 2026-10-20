"""Recall: the Claude Code hooks that bring memory into a prompt or a new session."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from conftest import append
from fixtures import claude_code_transcript, write_jsonl

from cogito_mem import recall
from cogito_mem.capture.claude_code import items_from_lines, project_of
from cogito_mem.errors import ApiError

SRC = str(Path(__file__).resolve().parents[1] / "src")


def prompt_hook(prompt: str, session: str = "now", cwd: str = "/work/app") -> dict:
    return {"hook_event_name": "UserPromptSubmit", "session_id": session, "cwd": cwd, "prompt": prompt,
            "transcript_path": f"/x/projects/-work-app/{session}.jsonl"}  # fmt: skip


def item(text: str, score: float, thread: str = "old", title: str | None = "/work/app", author: str = "user") -> dict:
    return {"text": text, "score": score, "author": author, "thread_id": thread, "valid_at": "2026-10-11T09:05:00.000Z",
            "source": {"id": "m", "title": title, "start": 0, "end": len(text)}}  # fmt: skip


class FakeClient:
    def __init__(self, items: list[dict] | None = None, error: Exception | None = None, delay: float = 0.0):
        self.items, self.error, self.delay = items or [], error, delay
        self.queries: list[dict] = []
        self.started = 0

    def query(self, text: str, namespace: str = "default", **kw) -> dict:
        self.queries.append({"text": text, "namespace": namespace, **kw})
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return {"items": self.items, "tokens": 0, "took_ms": 1.0}

    def start_in_background(self) -> bool:
        self.started += 1
        return True


def run_hook(hook: dict | str, client: FakeClient, **kw) -> str | None:
    body = hook if isinstance(hook, str) else json.dumps(hook)
    return recall.claude_code_hook(lambda: body, lambda: client, **kw)


# --------------------------------------------------------------------------- the project of an item


def test_project_of_a_working_directory():
    assert project_of("/work/app") == "/work/app"
    assert project_of("/work/app/") == "/work/app"
    assert project_of("/work/app/.claude/worktrees/brave-tesla-1a2b") == "/work/app"
    assert project_of("/work/app/.claude/worktrees/brave-tesla-1a2b/src") == "/work/app"
    assert project_of("C:\\work\\app\\.claude\\worktrees\\x") == "C:\\work\\app"
    assert project_of(None) is None and project_of("") is None


def test_captured_items_carry_the_project():
    records = claude_code_transcript()
    records[1] = {**records[1], "cwd": "/work/app/.claude/worktrees/brave-tesla", "gitBranch": "claude/brave-tesla"}
    records.append({"type": "user", "uuid": "no-cwd", "sessionId": "sess-1", "message": {"role": "user", "content": "hi"}})
    items = items_from_lines(enumerate(records))
    assert [it["title"] for it in items if it["client_ref"] != "claude-code:no-cwd"] == ["/work/app"] * 3
    assert "title" not in [it for it in items if it["client_ref"] == "claude-code:no-cwd"][0]


def test_a_query_returns_the_project_as_the_source_title(mem):
    append(mem, *[{k: v for k, v in it.items() if k != "valid_at"} for it in items_from_lines(enumerate(claude_code_transcript()))])  # fmt: skip
    found = mem.query("SQLite append-only log", max_tokens=1000)["items"]
    assert found and all(it["source"]["title"] == "/work/app" for it in found)


# --------------------------------------------------------------------------- UserPromptSubmit


def test_prompt_recall_keeps_items_above_the_threshold_from_other_sessions():
    client = FakeClient([
        item("we chose SQLite for the log", 0.95, thread="now"),  # this session: Claude has it already
        item("the log is append-only, enforced by triggers", 0.9),
        item("weak match about logs", 0.4),
        item("decided the log stays append only, with BM25 on by default", 0.7, thread="older"),
    ])  # fmt: skip
    out = run_hook(prompt_hook("why is the log append only?"), client, min_score=0.6)
    payload = json.loads(out)
    assert list(payload) == ["hookSpecificOutput"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "append-only, enforced by triggers" in context and "BM25 on by default" in context
    assert "chose SQLite" not in context and "weak match" not in context
    assert context.splitlines()[1].startswith("- [2026-10-1")  # each item with its date …
    assert ", user, this project] the log is append-only" in context  # … and its author
    assert client.queries[0]["text"] == "why is the log append only?"
    assert client.queries[0]["max_tokens"] >= recall.MAX_TOKENS  # room for this session's own items


def test_prompt_recall_puts_the_current_project_first_and_keeps_the_budget():
    client = FakeClient([
        item("other project: deploy with fly.io", 0.99, title="/work/site"),
        item("this project: deploy with docker", 0.8),
        item("a claude.ai chat about how to deploy", 0.75, title="Deploy ideas"),
        item("deploy " * 400, 0.7),
    ])  # fmt: skip
    context = json.loads(run_hook(prompt_hook("how do we deploy this?"), client))["hookSpecificOutput"]["additionalContext"]
    lines = context.splitlines()[1:]
    assert "this project: deploy with docker" in lines[0]
    assert ", project site] other project" in lines[1]
    assert ', "Deploy ideas"] a claude.ai chat' in lines[2]
    assert len(lines) == 3  # the long item does not fit in the 300 tokens left


def test_prompt_recall_cuts_a_first_item_that_is_over_the_budget():
    client = FakeClient([item("word list " * 500, 0.9)])
    context = json.loads(run_hook(prompt_hook("tell me about the word list"), client, max_tokens=50))
    text = context["hookSpecificOutput"]["additionalContext"]
    assert text.endswith(" …") and text.count("word") == 25


def test_prompt_recall_puts_messages_before_what_sessions_did():
    client = FakeClient([
        item("Ran `pytest tests/test_parser.py` (failed). Edited src/parser.py.", 0.95, author="actions"),
        item("The parser test must accept trailing commas.", 0.7),
        item("Edited " + ", ".join(f"tests/test_parser_{i}.py" for i in range(200)) + ".", 0.9, author="actions"),
        item("The parser test for dates is slow.", 0.65, title="/work/site"),
    ])  # fmt: skip
    out = json.loads(run_hook(prompt_hook("why does the parser test fail?"), client))
    lines = out["hookSpecificOutput"]["additionalContext"].splitlines()[1:]
    assert "must accept trailing commas" in lines[0]
    assert ", actions, this project] Ran `pytest tests/test_parser.py` (failed)" in lines[1]
    assert "for dates is slow" in lines[2]  # the current project first, then messages before actions in each
    assert len(lines) == 3  # the long list of edits does not fit in the room the messages left


def test_prompt_recall_needs_enough_of_the_prompts_words():
    prompt = prompt_hook("fix the CSS of the login button on the settings page")  # 6 content words: 3 needed
    client = FakeClient([
        item("Fixing a missing button style, then checking the page.", 1.0),  # shares 2: a rank, not a match
        item("The login button CSS on the settings page is fixed now.", 0.7),
    ])  # fmt: skip
    context = json.loads(run_hook(prompt, client))["hookSpecificOutput"]["additionalContext"]
    assert "login button CSS" in context and "missing button style" not in context
    long_prompt = " ".join(f"word{i}" for i in range(20))  # 20 content words: 4 needed
    assert run_hook(prompt_hook(long_prompt), FakeClient([item("word1 word2 word3", 0.9)])) is None
    assert run_hook(prompt_hook(long_prompt), FakeClient([item("word1 word2 word3 word4", 0.9)])) is not None
    assert run_hook(prompt_hook("what about Odra?"), FakeClient([item("Odra is busy", 0.9)])) is not None  # 1 of 1


def test_prompt_recall_says_nothing_when_nothing_qualifies():
    assert run_hook(prompt_hook("what about the parser?"), FakeClient([item("the parser", 0.3)])) is None
    assert run_hook(prompt_hook("what about the parser?"), FakeClient([item("the parser", 0.9, thread="now")])) is None
    client = FakeClient([item("the parser", 0.9)])
    assert run_hook(prompt_hook("yes"), client) is None  # too short to look up
    assert run_hook(prompt_hook("/review the open PR"), client) is None  # a slash command
    assert client.queries == []


def test_prompt_recall_with_a_real_memory(mem):
    append(mem,
           {"author": "user", "thread_id": "s1", "title": "/work/app", "text": "The parser must accept trailing commas."},
           {"author": "assistant", "thread_id": "now", "title": "/work/app", "text": "Trailing commas in the parser: done."},
           {"author": "user", "thread_id": "s2", "title": "/work/app", "text": "Lunch is at noon on Friday."})  # fmt: skip
    assert mem.flush(10)
    out = run_hook(prompt_hook("does the parser accept trailing commas?"), mem, min_score=0.6)
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "must accept trailing commas" in context
    assert "done." not in context  # from this session
    assert "Lunch" not in context  # below the threshold: only one of the two searches found it


def test_prompt_recall_errors_and_timeouts_print_nothing(tmp_path):
    log = tmp_path / "recall.log"
    hook = prompt_hook("what did we decide about the parser?")
    assert run_hook(hook, FakeClient(error=ApiError("unavailable", "not running")), log=log) is None
    t0 = time.monotonic()
    assert run_hook(hook, FakeClient([item("x", 0.9)], delay=3.0), timeout=0.2, log=log) is None
    assert time.monotonic() - t0 < 1.5
    assert run_hook("not json", FakeClient(), log=log) is None
    assert run_hook("[1, 2]", FakeClient(), log=log) is None
    assert run_hook({"hook_event_name": "Stop"}, FakeClient()) is None
    lines = log.read_text().splitlines()
    assert "UserPromptSubmit: ApiError" in lines[0] and "UserPromptSubmit: TimeoutError" in lines[1]
    assert len(lines) == 4


def test_recall_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("COGITO_MEM_RECALL", "off")
    client = FakeClient([item("x y", 0.9)])
    assert run_hook(prompt_hook("what about the parser then?"), client) is None
    assert client.queries == []


def test_the_threshold_comes_from_the_environment(monkeypatch):
    client = FakeClient([item("the parser accepts commas", 0.7)])
    monkeypatch.setenv("COGITO_MEM_RECALL_MIN_SCORE", "0.8")
    assert run_hook(prompt_hook("what about the parser then?"), client) is None
    monkeypatch.setenv("COGITO_MEM_RECALL_MIN_SCORE", "0.5")
    assert run_hook(prompt_hook("what about the parser then?"), client) is not None


def test_recall_command_never_fails_the_prompt(tmp_path):
    env = {**os.environ, "PYTHONPATH": SRC, "COGITO_MEM_URL": "http://127.0.0.1:9"}  # nothing listens there
    for stdin in (json.dumps(prompt_hook("what did we decide about the parser?")), "garbage", ""):
        out = subprocess.run([sys.executable, "-m", "cogito_mem", "--root", str(tmp_path / "h"), "recall", "claude-code"],
                             input=stdin, capture_output=True, text=True, env=env, timeout=30)  # fmt: skip
        assert out.returncode == 0 and out.stdout == ""


def test_recall_command_prints_the_hook_json(tmp_path):
    from cogito_mem.memory import Memory
    from cogito_mem.server import MemoryServer

    memory = Memory(None, embedder="hash")
    append(memory, {"author": "user", "thread_id": "s1", "title": "/work/app", "text": "The parser must accept trailing commas."},
           namespace="work-hollow")  # fmt: skip
    assert memory.flush(10)
    server =MemoryServer(memory, host="127.0.0.1", port=0)
    threading.Thread(target=server.serve, daemon=True).start()
    try:
        env = {**os.environ, "PYTHONPATH": SRC, "COGITO_MEM_URL": server.url, "COGITO_MEM_NAMESPACE": "work-hollow"}
        out = subprocess.run([sys.executable, "-m", "cogito_mem", "--root", str(tmp_path / "h"), "recall", "claude-code"],
                             input=json.dumps(prompt_hook("does the parser accept trailing commas?")),
                             capture_output=True, text=True, env=env, timeout=30)  # fmt: skip
    finally:
        server.shutdown()
        memory.close()
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "must accept trailing commas" in payload["hookSpecificOutput"]["additionalContext"]


# --------------------------------------------------------------------------- SessionStart


def session(path: Path, sid: str, day: str, cwd: str = "/work/app", mtime: float | None = None) -> Path:
    records = claude_code_transcript(sid, day)
    for rec in records:
        if "cwd" in rec:
            rec["cwd"] = cwd
    write_jsonl(path / f"{sid}.jsonl", records)
    if mtime is not None:
        os.utime(path / f"{sid}.jsonl", (mtime, mtime))
    return path / f"{sid}.jsonl"


def start_hook(projects: Path, sid: str = "now", cwd: str = "/work/app", source: str = "startup") -> dict:
    return {"hook_event_name": "SessionStart", "session_id": sid, "cwd": cwd, "source": source,
            "transcript_path": str(projects / "-work-app" / f"{sid}.jsonl")}  # fmt: skip


def test_session_start_brings_the_end_of_the_last_session_in_this_project(tmp_path):
    projects = tmp_path / "projects"
    now = time.time()
    session(projects / "-work-app", "older", "2026-10-01", mtime=now - 3000)
    session(projects / "-work-app--claude-worktrees-brave", "in-worktree", "2026-10-02",
            cwd="/work/app/.claude/worktrees/brave", mtime=now - 2000)  # fmt: skip
    session(projects / "-work-app", "other-project", "2026-10-03", cwd="/work-app", mtime=now - 1000)  # same folder name
    session(projects / "-work-site", "elsewhere", "2026-10-04", cwd="/work/site", mtime=now - 500)
    session(projects / "-work-app", "now", "2026-10-05", mtime=now)  # the session that is starting

    client = FakeClient()
    out = run_hook(start_hook(projects), client)
    payload = json.loads(out)["hookSpecificOutput"]
    assert payload["hookEventName"] == "SessionStart"
    context = payload["additionalContext"]
    assert context.startswith("cogito-mem: the last session in this project (in-worktree, 2026-10-0")
    assert "user: Let's plan the storage layer" in context
    assert "assistant: Sure. SQLite with an append-only log" in context
    assert "user: Idea: call the mascot Cogi. My key is [redacted]" in context
    assert client.started == 1  # the service is started for the prompts to come


def test_session_start_with_no_earlier_session(tmp_path):
    projects = tmp_path / "projects"
    session(projects / "-work-app", "now", "2026-10-05")
    client = FakeClient()
    assert run_hook(start_hook(projects), client) is None
    assert client.started == 1


def test_session_start_keeps_each_prompt_with_its_last_reply(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    base = {"sessionId": "old", "cwd": "/work/app", "timestamp": "2026-10-01T10:00:00Z"}
    records = []
    for i in range(40):
        records += [
            {**base, "type": "user", "uuid": f"u{i}", "message": {"role": "user", "content": f"prompt {i} " + "x" * 1200}},
            {**base, "type": "assistant", "uuid": f"p{i}", "message": {"role": "assistant", "content": f"working on {i}"}},
            {**base, "type": "user", "uuid": f"t{i}", "message": {"role": "user", "content": [{"type": "tool_result", "content": "y" * 3000}]}},
            {**base, "type": "assistant", "uuid": f"a{i}", "message": {"role": "assistant", "content": f"done with {i}"}},
        ]  # fmt: skip
    write_jsonl(projects / "-work-app" / "old.jsonl", records)
    monkeypatch.setattr(recall, "TAIL_BYTES", 2000)  # the end is read in growing steps
    lines = recall.session_start_context(start_hook(projects)).splitlines()[1:]
    assert [line.split(" x")[0] for line in lines] == [
        "user: prompt 37", "assistant: done with 37", "user: prompt 38", "assistant: done with 38",
        "user: prompt 39", "assistant: done with 39",
    ]  # fmt: skip
    assert lines[0].endswith(" …")  # each message cut to its share
