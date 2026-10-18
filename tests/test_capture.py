"""Capture: Claude Code transcripts, Codex session files, claude.ai and ChatGPT exports."""

from __future__ import annotations

import json
import zipfile

from conftest import query
from fixtures import (
    chatgpt_export,
    claude_code_transcript,
    claude_export,
    codex_rollout,
    codex_rollout_old,
    write_jsonl,
)

from cogito_mem.capture import read_new_lines, redact
from cogito_mem.capture import claude_code, codex, exports


def test_redact_common_secrets():
    text = (
        "keys: sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA0123 ghp_abcdefghijklmnopqrstuvwxyz0123456789 "
        "AKIAABCDEFGHIJKLMNOP password=hunter2hunter2 api_key: 'abcd1234efgh' "
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY----- keep this"
    )
    out = redact(text)
    for secret in ("sk-ant-api03", "ghp_", "AKIAABCD", "hunter2", "abcd1234efgh", "MIIEow"):
        assert secret not in out
    assert "password=[redacted]" in out and "keep this" in out


def test_read_new_lines_only_returns_complete_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text('{"a": 1}\n{"b": 2}\n{"c": 3')
    lines, offset, line = read_new_lines(path)
    assert [n for n, _ in lines] == [0, 1] and line == 2
    with open(path, "a") as fh:
        fh.write("}\n")
    more, offset2, line2 = read_new_lines(path, offset, line)
    assert more == [(2, '{"c": 3}')] and line2 == 3 and offset2 == path.stat().st_size


def test_claude_code_transcript_keeps_only_the_conversation(tmp_path, mem):
    path = write_jsonl(tmp_path / "proj" / "sess-1.jsonl", claude_code_transcript())
    counts = claude_code.capture_transcript(mem, path, tmp_path / "state", "sess-1")
    assert counts == {"added": 3, "duplicate": 0}
    items = query(mem, "storage mascot plan SQLite", top_k=10, max_tokens=1000)["items"]
    texts = sorted(i["text"] for i in items)
    assert texts == [
        "Idea: call the mascot Cogi. My key is [redacted]",
        "Let's plan the storage layer for the memory.",
        "Sure. SQLite with an append-only log table works well.",
    ]
    assert {i["thread_id"] for i in items} == {"sess-1"}
    assert {i["author"] for i in items} == {"user", "assistant"}
    idea = [i for i in items if "mascot" in i["text"]][0]
    assert idea["valid_at"] == "2026-10-11T09:05:00.000Z"
    # running the hook again adds nothing; new lines are picked up
    assert claude_code.capture_transcript(mem, path, tmp_path / "state", "sess-1") == {"added": 0, "duplicate": 0}
    with open(path, "a") as fh:
        fh.write(json.dumps({"type": "user", "uuid": "late", "sessionId": "sess-1", "timestamp": "2026-10-11T10:00:00Z",
                             "message": {"role": "user", "content": "one more thing"}}) + "\n")  # fmt: skip
    assert claude_code.capture_transcript(mem, path, tmp_path / "state", "sess-1") == {"added": 1, "duplicate": 0}
    # a lost cursor only costs duplicates, never double entries
    assert claude_code.capture_transcript(mem, path, tmp_path / "other-state", "sess-1") == {"added": 0, "duplicate": 4}


def test_claude_code_backfill_is_imported_history(tmp_path, mem):
    projects = tmp_path / "projects"
    write_jsonl(projects / "-work-app" / "sess-a.jsonl", claude_code_transcript("sess-a", "2026-09-01"))
    write_jsonl(projects / "-work-app" / "sess-b.jsonl", claude_code_transcript("sess-b", "2026-09-02"))
    totals = claude_code.capture_all(mem, tmp_path / "state", root=projects)
    assert totals == {"added": 6, "duplicate": 0, "files": 2}
    first = query(mem, "storage layer", as_of="2026-09-01T12:00:00Z", max_tokens=1000)["items"]
    assert {i["thread_id"] for i in first} == {"sess-a"}  # as_of sees the history as it was then


def test_codex_session_files(tmp_path, mem):
    home = tmp_path / "codex"
    new = write_jsonl(home / "sessions" / "2026" / "10" / "12" / "rollout-2026-10-12T10-00-00-abc.jsonl", codex_rollout())
    write_jsonl(home / "sessions" / "2025" / "08" / "01" / "rollout-old.jsonl", codex_rollout_old())
    totals = codex.sweep(mem, tmp_path / "state", since_days=None, home=home)
    assert totals == {"added": 4, "duplicate": 0, "files": 2}
    items = query(mem, "parser time zone old format hello", top_k=10, max_tokens=1000)["items"]
    by_text = {i["text"]: i for i in items}
    assert set(by_text) == {
        "Fix the flaky date parser test",
        "Fixed: the parser now requires a time zone.",
        "hello from the old format",
        "hi, old format",
    }
    assert by_text["Fix the flaky date parser test"]["thread_id"] == "0199a-codex"
    assert by_text["Fix the flaky date parser test"]["valid_at"] == "2026-10-12T10:00:02.000Z"
    assert by_text["hi, old format"]["thread_id"] == "old-sess"
    # a later turn in the same file
    with open(new, "a") as fh:
        fh.write(json.dumps({"timestamp": "2026-10-12T10:01:00.000Z", "type": "event_msg",
                             "payload": {"type": "user_message", "message": "and add a test"}}) + "\n")  # fmt: skip
    assert codex.sweep(mem, tmp_path / "state", since_days=None, home=home) == {"added": 1, "duplicate": 0, "files": 2}


def test_claude_ai_export_zip(tmp_path, mem):
    path = tmp_path / "data-2025.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("conversations.json", json.dumps(claude_export()))
        zf.writestr("users.json", "[]")
    counts = exports.import_export(mem, "claude", path)
    assert counts == {"added": 2, "duplicate": 0, "conversations": 1}
    assert exports.import_export(mem, "claude", path)["duplicate"] == 2  # importing twice adds nothing
    item = query(mem, "raised beds soil", max_tokens=1000, as_of="2025-05-02T00:00:00Z")["items"][0]
    assert item["source"]["title"] == "Garden plans" and item["thread_id"] == "conv-1"


def test_chatgpt_export_follows_the_shown_branch(tmp_path, mem):
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(chatgpt_export()))
    counts = exports.import_export(mem, "chatgpt", path)
    assert counts == {"added": 2, "duplicate": 0, "conversations": 1}
    items = query(mem, "Kraków castle see branch", max_tokens=1000)["items"]
    assert sorted(i["text"] for i in items) == ["Wawel Castle and the Main Square.", "What should I see in Kraków?"]
    user = [i for i in items if i["author"] == "user"][0]
    assert user["valid_at"] == "2024-05-01T08:00:01.500Z" and user["source"]["title"] == "Trip to Kraków"
