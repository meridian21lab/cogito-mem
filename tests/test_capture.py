"""Capture: Claude Code transcripts, Codex session files, claude.ai and ChatGPT exports."""

from __future__ import annotations

import io
import json
import zipfile

from conftest import query
from fixtures import (
    chatgpt_export,
    claude_code_tool_work,
    claude_code_transcript,
    claude_export,
    codex_rollout,
    codex_rollout_old,
    write_jsonl,
)

from cogito_mem.capture import read_new_lines, redact
from cogito_mem.capture import claude_code, codex, exports


def test_redact_common_secrets():
    # samples that can't be real keys (EXAMPLE, xxxx): the plugin directory refuses a file that holds a real-looking one
    text = (
        "keys: sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxx ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx "
        "AKIAIOSFODNN7EXAMPLE password=EXAMPLE-password api_key: 'YOUR_API_KEY' "
        "-----BEGIN RSA PRIVATE KEY-----\nEXAMPLE\n-----END RSA PRIVATE KEY----- keep this"
    )
    assert redact(text) == (
        "keys: [redacted] [redacted] [redacted] password=[redacted] api_key: '[redacted]' [redacted] keep this"
    )
    command = redact(
        "MY_SERVICE_API_KEY=xxxxxxxxxxxxxxxx curl -H 'Authorization: Bearer xxxxxxxxxxxxxxxxxxxx' "
        "https://bob:EXAMPLE@example.com/x http://localhost:7327/v1"
    )
    assert command == (
        "MY_SERVICE_API_KEY=[redacted] curl -H 'Authorization: Bearer [redacted]' "
        "https://bob:[redacted]@example.com/x http://localhost:7327/v1"
    )


def test_read_new_lines_only_returns_complete_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text('{"a": 1}\n{"b": 2}\n{"c": 3')
    lines, offset, line = read_new_lines(path)
    assert [n for n, _ in lines] == [0, 1] and line == 2
    with open(path, "a") as fh:
        fh.write("}\n")
    more, offset2, line2 = read_new_lines(path, offset, line)
    assert more == [(2, '{"c": 3}')] and line2 == 3 and offset2 == path.stat().st_size


def test_claude_code_transcript_keeps_the_conversation_and_what_it_did(tmp_path, mem):
    path = write_jsonl(tmp_path / "proj" / "sess-1.jsonl", claude_code_transcript())
    counts = claude_code.capture_transcript(mem, path, tmp_path / "state", "sess-1")
    assert counts == {"added": 4, "duplicate": 0}
    items = query(mem, "storage mascot plan SQLite ran", top_k=10, max_tokens=1000)["items"]
    texts = sorted(i["text"] for i in items)
    assert texts == [
        "Idea: call the mascot Cogi. My key is [redacted]",
        "Let's plan the storage layer for the memory.",
        "Ran `ls`.",
        "Sure. SQLite with an append-only log table works well.",
    ]  # not the summary Claude Code wrote when it compacted the session
    assert {i["thread_id"] for i in items} == {"sess-1"}
    assert {i["author"] for i in items} == {"user", "assistant", "actions"}
    idea = [i for i in items if "mascot" in i["text"]][0]
    assert idea["valid_at"] == "2026-10-11T09:05:00.000Z"
    # running the hook again adds nothing; new lines are picked up
    assert claude_code.capture_transcript(mem, path, tmp_path / "state", "sess-1") == {"added": 0, "duplicate": 0}
    with open(path, "a") as fh:
        fh.write(json.dumps({"type": "user", "uuid": "late", "sessionId": "sess-1", "timestamp": "2026-10-11T10:00:00Z",
                             "message": {"role": "user", "content": "one more thing"}}) + "\n")  # fmt: skip
    assert claude_code.capture_transcript(mem, path, tmp_path / "state", "sess-1") == {"added": 1, "duplicate": 0}
    # a lost cursor only costs duplicates, never double entries
    assert claude_code.capture_transcript(mem, path, tmp_path / "other-state", "sess-1") == {"added": 0, "duplicate": 5}


def test_claude_code_skips_the_compaction_summary():
    records = claude_code_transcript()
    summary = [r for r in records if r.get("isCompactSummary")]
    assert summary and "storage layer" in summary[0]["message"]["content"]
    texts = [it["text"] for it in claude_code.items_from_lines(enumerate(records), actions=True)]
    assert not any("continued from a previous conversation" in t or "Summary:" in t for t in texts)
    del summary[0]["isCompactSummary"]  # the text alone gives it away too
    assert len(claude_code.items_from_lines(enumerate(records))) == 3


def test_claude_code_backfill_is_imported_history(tmp_path, mem):
    projects = tmp_path / "projects"
    write_jsonl(projects / "-work-app" / "sess-a.jsonl", claude_code_transcript("sess-a", "2026-09-01"))
    write_jsonl(projects / "-work-app" / "sess-b.jsonl", claude_code_transcript("sess-b", "2026-09-02"))
    totals = claude_code.capture_all(mem, tmp_path / "state", root=projects)
    assert totals == {"added": 8, "duplicate": 0, "files": 2}
    first = query(mem, "storage layer", as_of="2026-09-01T12:00:00Z", max_tokens=1000)["items"]
    assert {i["thread_id"] for i in first} == {"sess-a"}  # as_of sees the history as it was then


ACTION_1 = (
    "Ran `python -m pytest -q tests/test_parser.py` (failed), `python -m pytest -q tests/test_parser.py`, "
    "`OPENROUTER_API_KEY=[redacted] ./deploy.sh staging`, `rm -rf build` (not run). "
    "Edited src/parser.py. Read /home/me/notes/parser.md."
)


def test_claude_code_actions_one_item_per_turn():
    items = claude_code.items_from_lines(enumerate(claude_code_tool_work()), "sess-t", actions=True)
    assert [(it["author"], it["text"]) for it in items] == [
        ("user", "The parser test fails on trailing commas, please fix it."),
        ("assistant", "Let me run the tests first."),
        ("actions", ACTION_1),  # where the turn's first tool call was
        ("assistant", "Fixed: the parser accepts trailing commas now."),
        ("user", "Thanks. Note it in the README."),
        ("actions", "Wrote README.md."),
        ("assistant", "Done."),
    ]
    first = items[2]
    assert first["client_ref"] == "claude-code:sess-t-c1:actions"
    assert first["thread_id"] == "sess-t" and first["title"] == "/work/app"
    assert first["valid_at"] == "2026-10-12T10:01:10.000Z"
    assert "the whole file" not in items[5]["text"] and "3 passed" not in first["text"]  # never what tools returned
    messages = claude_code.items_from_lines(enumerate(claude_code_tool_work()))  # as recall reads them
    assert messages == [it for it in items if it["author"] != "actions"]


def test_claude_code_actions_failures_and_cap():
    records = claude_code_tool_work()
    result = [r for r in records if r["uuid"] == "sess-t-r7"][0]["message"]["content"][0]
    result["content"] = [{"type": "text", "text": "Exit code 2\nno such stage"}]  # no is_error, but an exit code
    text = claude_code.items_from_lines(enumerate(records), actions=True)[2]["text"]
    assert "`OPENROUTER_API_KEY=[redacted] ./deploy.sh staging` (failed)," in text

    base = {"type": "assistant", "sessionId": "s", "cwd": "/w", "timestamp": "2026-10-12T10:00:00Z"}
    busy = [{"type": "user", "uuid": "p", "sessionId": "s", "message": {"role": "user", "content": "go"}}]
    for i in range(150):  # a long turn: 75 commands, 75 edits
        if i % 2:
            name, args = "Bash", {"command": f"step-{i} " + "x" * 200 + "\nsecond line"}
        else:
            name, args = "Edit", {"file_path": f"/w/src/m{i}.py"}
        use = {"type": "tool_use", "id": f"t{i}", "name": name, "input": args}
        busy.append({**base, "uuid": f"c{i}", "message": {"content": [use]}})
    (item,) = [it for it in claude_code.items_from_lines(enumerate(busy), actions=True) if it["author"] == "actions"]
    assert len(item["text"]) <= claude_code.ACTION_CHARS
    assert item["text"].startswith("Ran `step-1 xxx") and "x …`, `step-3 " in item["text"]  # each command cut short
    assert " more. Edited src/m0.py, src/m2.py, " in item["text"] and item["text"].endswith(" more.")  # fmt: skip


def test_claude_code_actions_are_captured_once(tmp_path, mem):
    records = claude_code_tool_work()
    path = tmp_path / "proj" / "sess-t.jsonl"
    middle = [r["uuid"] for r in records].index("sess-t-r3") + 1  # the hook ran in the middle of the first turn
    write_jsonl(path, records[:middle])
    state = tmp_path / "state"
    assert claude_code.capture_transcript(mem, path, state, "sess-t") == {"added": 3, "duplicate": 0}
    with open(path, "a") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in records[middle:]))
    assert claude_code.capture_transcript(mem, path, state, "sess-t") == {"added": 5, "duplicate": 0}
    assert claude_code.capture_transcript(mem, path, state, "sess-t") == {"added": 0, "duplicate": 0}
    # a lost cursor reads the first turn whole: its item is the one already stored, not a second copy
    assert claude_code.capture_transcript(mem, path, tmp_path / "lost", "sess-t") == {"added": 0, "duplicate": 7}
    found = query(mem, "ran edited wrote read", filter={"author": "actions"}, top_k=10, max_tokens=2000)["items"]
    assert sorted(i["text"] for i in found) == [
        "Ran `python -m pytest -q tests/test_parser.py` (failed). Read src/parser.py.",  # the hook's first read
        "Ran `python -m pytest -q tests/test_parser.py`, `OPENROUTER_API_KEY=[redacted] ./deploy.sh staging`, "
        "`rm -rf build` (not run). Edited src/parser.py. Read /home/me/notes/parser.md.",  # and the rest of the turn
        "Wrote README.md.",
    ]


def test_claude_code_actions_can_be_turned_off(tmp_path, mem, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_CAPTURE_ACTIONS", "off")
    path = write_jsonl(tmp_path / "proj" / "sess-t.jsonl", claude_code_tool_work())
    assert claude_code.capture_transcript(mem, path, tmp_path / "state", "sess-t") == {"added": 5, "duplicate": 0}
    assert query(mem, "ran edited wrote read", filter={"author": "actions"}, max_tokens=1000)["items"] == []


def test_private_text_is_not_stored():
    base = {"type": "user", "sessionId": "s", "cwd": "/w"}
    records = [
        {**base, "uuid": "u1", "message": {"content": "Deploy to staging. <private>The root password is swordfish.</private> Then smoke-test."}},
        {**base, "uuid": "u2", "message": {"content": "<private>my bank PIN is 1234</private>\n"}},
        {**base, "type": "assistant", "uuid": "a1", "message": {"content": [{"type": "text", "text": "Noted <PRIVATE>swordfish</PRIVATE>."}]}},
        {**base, "uuid": "u3", "message": {"content": "Remember this: <private>a tag left open hides the rest"}},
    ]  # fmt: skip
    assert [it["text"] for it in claude_code.items_from_lines(enumerate(records))] == [
        "Deploy to staging.  Then smoke-test.",
        "Noted .",
        "Remember this:",
    ]
    said = {"type": "event_msg", "payload": {"type": "user_message", "message": "ok <private>pin 1234</private>"}}
    assert [it["text"] for it in codex.items_from_records([(0, said)], "c", use_events=True)] == ["ok"]


def test_capture_can_be_paused(tmp_path, isolated_env, monkeypatch, capsys):
    from cogito_mem.cli import main

    monkeypatch.setenv("COGITO_MEM_CAPTURE", "off")
    root = tmp_path / "cogito-home"
    path = write_jsonl(tmp_path / "proj" / "sess-1.jsonl", claude_code_transcript())
    assert main(["--root", str(root), "capture", "claude-code", "--transcript", str(path), "--wait"]) == 0
    hook = {"session_id": "sess-1", "transcript_path": str(path), "hook_event_name": "Stop"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(hook)))
    assert main(["--root", str(root), "capture", "claude-code"]) == 0
    assert main(["--root", str(root), "capture", "codex"]) == 0
    assert capsys.readouterr().out == ""
    assert not (root / "run").exists()  # no cursor, no background process, no service


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
