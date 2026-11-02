"""Capture: Claude Code transcripts, Codex session files, claude.ai and ChatGPT exports."""

from __future__ import annotations

import io
import json
import os
import threading
import time
import zipfile
from pathlib import Path

import pytest
from conftest import query
from fixtures import (
    chatgpt_export,
    claude_code_subagent,
    claude_code_tool_work,
    claude_code_transcript,
    claude_export,
    codex_rollout,
    codex_rollout_old,
    write_jsonl,
)

from cogito_mem import Memory
from cogito_mem.capture import read_new_lines, redact
from cogito_mem.capture import claude_code, codex, exports

SRC = str(Path(__file__).resolve().parents[1] / "src")


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


def test_claude_code_actions_are_captured_once(tmp_path, mem, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_CAPTURE_TOOL_OUTPUT", "off")
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
    assert claude_code.capture_transcript(mem, path, tmp_path / "state", "sess-t") == {"added": 9, "duplicate": 0}  # 5 + 4 tool
    assert query(mem, "ran edited wrote read", filter={"author": "actions"}, max_tokens=1000)["items"] == []


# --------------------------------------------------------------------------- what sub-agents handed back


def subagent_session(tmp_path) -> tuple:
    project = tmp_path / "projects" / "-work-app"
    main = write_jsonl(project / "sess-1.jsonl", claude_code_transcript())
    agents = project / "sess-1" / "subagents"
    write_jsonl(agents / "agent-a1.jsonl", claude_code_subagent("a1"))
    write_jsonl(agents / "agent-a2.jsonl", claude_code_subagent("a2", handback=True))
    write_jsonl(agents / "agent-acompact-1.jsonl", claude_code_subagent("compaction"))
    return main, agents


def test_subagent_reports_from_their_own_files(tmp_path, mem):
    main, agents = subagent_session(tmp_path)
    counts = claude_code.capture_transcript(mem, main, tmp_path / "state", "sess-1")
    assert counts == {"added": 6, "duplicate": 0}  # the 4 of the session, one report per sub-agent
    found = query(mem, "report parser slow long lines", filter={"author": "subagent"}, max_tokens=1000)["items"]
    assert sorted(i["text"] for i in found) == [
        "Report of a1: the parser is slow on long lines.",
        "Report of a2: the parser is slow on long lines.",
    ]
    assert {i["thread_id"] for i in found} == {"sess-1"}  # the parent session's
    assert {i["source"]["title"] for i in found} == {"/work/app"}  # a worktree counts as its repository
    # reading again adds nothing, and a sub-agent that finishes later is picked up
    assert claude_code.capture_transcript(mem, main, tmp_path / "state", "sess-1") == {"added": 0, "duplicate": 0}
    write_jsonl(agents / "agent-a3.jsonl", claude_code_subagent("a3"))
    assert claude_code.capture_transcript(mem, main, tmp_path / "state", "sess-1") == {"added": 1, "duplicate": 0}
    # a lost cursor only costs duplicates
    assert claude_code.capture_transcript(mem, main, tmp_path / "lost", "sess-1") == {"added": 0, "duplicate": 7}


def test_subagent_keeps_only_its_report():
    for handback in (False, True):
        records = claude_code_subagent("a1", handback=handback)
        items = claude_code.items_from_lines(enumerate(records), "sess-1", actions=True, tool_output=True, subagents=True)
        assert [(it["author"], it["text"]) for it in items] == [("subagent", "Report of a1: the parser is slow on long lines.")]
        assert items[0]["client_ref"] == "claude-code:a1-a3" and items[0]["thread_id"] == "sess-1"
        assert items[0]["valid_at"] == "2026-10-11T09:30:04.000Z"
    assert claude_code.items_from_lines(enumerate(claude_code_subagent("a1"))) == []  # as recall reads them


def test_subagent_turns_in_the_session_transcript(tmp_path, mem):
    records = claude_code_transcript() + claude_code_subagent("a1")
    path = write_jsonl(tmp_path / "proj" / "sess-1.jsonl", records)
    assert claude_code.capture_transcript(mem, path, tmp_path / "state", "sess-1") == {"added": 5, "duplicate": 0}
    found = query(mem, "report parser", filter={"author": "subagent"}, max_tokens=1000)["items"]
    assert [i["text"] for i in found] == ["Report of a1: the parser is slow on long lines."]


def test_subagent_still_at_work_has_no_report_yet(tmp_path, mem):
    main, agents = subagent_session(tmp_path)
    records = claude_code_subagent("a1")
    write_jsonl(agents / "agent-a1.jsonl", records[:-1])
    assert claude_code.capture_transcript(mem, main, tmp_path / "state", "sess-1") == {"added": 5, "duplicate": 0}
    with open(agents / "agent-a1.jsonl", "a") as fh:
        fh.write(json.dumps(records[-1]) + "\n")
    assert claude_code.capture_transcript(mem, main, tmp_path / "state", "sess-1") == {"added": 1, "duplicate": 0}


def test_subagent_report_is_redacted(tmp_path):
    records = claude_code_subagent("a1")
    records[-1]["message"]["content"][0]["text"] = "Done. <private>pin 1234</private>Key: sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxx"
    (item,) = claude_code.items_from_lines(enumerate(records), subagents=True)
    assert item["text"] == "Done. Key: [redacted]"


def test_subagent_reports_can_be_turned_off(tmp_path, mem, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_CAPTURE_SUBAGENTS", "off")
    main, _ = subagent_session(tmp_path)
    assert claude_code.capture_transcript(mem, main, tmp_path / "state", "sess-1") == {"added": 4, "duplicate": 0}


# --------------------------------------------------------------------------- what tools returned, by rule


def tool_run(command: str | None, output: str, error: bool = False, name: str = "Bash", args: dict | None = None) -> list[dict]:
    args = args if args is not None else {"command": command}
    base = {"sessionId": "s", "cwd": "/work/app", "timestamp": "2026-10-12T10:00:00.000Z"}
    result = {"type": "tool_result", "tool_use_id": "t1", "content": output, **({"is_error": True} if error else {})}
    return [
        {**base, "type": "assistant", "uuid": "c1", "message": {"content": [{"type": "tool_use", "id": "t1", "name": name, "input": args}]}},
        {**base, "type": "user", "uuid": "r1", "message": {"content": [result]}},
    ]  # fmt: skip


def kept(*args, **kw) -> list[str]:
    return [it["text"] for it in claude_code.items_from_lines(enumerate(tool_run(*args, **kw)), tool_output=True)]


def test_tool_output_of_the_fixture_session():
    items = claude_code.items_from_lines(enumerate(claude_code_tool_work()), "sess-t", tool_output=True)
    tools = [it for it in items if it["author"] == "tool"]
    assert [it["text"] for it in tools] == [
        "`python -m pytest -q tests/test_parser.py` (failed):\nFAILED tests/test_parser.py::test_commas",
        "Edit tests/test_parser.py (not run):\n<tool_use_error>String to replace not found in file.</tool_use_error>",
        "`python -m pytest -q tests/test_parser.py`:\n3 passed in 0.12s",
        "`rm -rf build` (not run):\nThe user doesn't want to proceed with this tool use. The tool use was rejected.",
    ]
    assert tools[0]["client_ref"] == "claude-code:sess-t-r1:tool:toolu_1"
    assert tools[0]["thread_id"] == "sess-t" and tools[0]["title"] == "/work/app"
    assert tools[0]["valid_at"] == "2026-10-12T10:01:20.000Z"
    assert not any("the whole file" in it["text"] or "def parse" in it["text"] or "notes" in it["text"] for it in tools)


def test_tool_output_a_failed_command_keeps_its_end():
    output = "Exit code 1\n" + "\n".join(f"step {i}" for i in range(30))
    assert kept("make all", output, error=True) == ["`make all` (failed):\n" + "\n".join(f"step {i}" for i in range(20, 30))]
    assert kept("make all", "Exit code 1", error=True) == []  # the actions note already says it failed
    # an error further up comes along
    assert kept("make", "Traceback (most recent call last):\n" + "x\n" * 30 + "done", error=True)[0].startswith(
        "`make` (failed):\nTraceback (most recent call last):\nx\ndone")  # fmt: skip


def test_tool_output_lines_that_carry_a_metric_or_an_error():
    noise = "compiling the thing\n"
    for line in ("12 passed, 1 failed in 3.40s", "Error: no such stage", "ValueError: bad input", "loss=0.312",
                 "accuracy: 0.97", "coverage 87%", "took 12 ms", "FAILED tests/a.py::t", "fatal: not a git repository"):  # fmt: skip
        assert kept("run", noise + line + "\n" + noise) == [f"`run`:\n{line}"], line
    for line in ("a.py", "main.py:12: def f():", "merged the branch", "see https://x.y/z?a=b", "PATH=/usr/bin", "12:30:45 started"):
        assert kept("run", noise + line + "\n" + noise) == [], line


def test_tool_output_of_a_long_success_keeps_its_last_lines():
    output = "\n".join(f"step {i}" for i in range(20))
    assert kept("make", output) == ["`make`:\nstep 18\nstep 19"]
    assert kept("make", "\n".join(f"step {i}" for i in range(5))) == []  # short, and nothing in it to keep


def test_tool_output_never_keeps_file_contents():
    secret_file = "12 passed\nError: this line is in a file\nkey=1\n" * 10
    assert kept(None, secret_file, name="Read", args={"file_path": "/work/app/a.py"}) == []
    assert kept(None, "boom: " + secret_file, error=True, name="Read", args={"file_path": "/work/app/a.py"}) == []
    for command in ("cat a.py", "head -50 a.py", "sed -n 1,9p a.py", "grep -n Error a.py", "cd /other && cat a.py",
                    "git diff", "git -C /work/app show HEAD"):  # fmt: skip
        assert kept(command, secret_file) == [], command
    assert kept(None, secret_file, name="WebFetch", args={"url": "https://x.y"}) == []  # no command: only its failure
    assert kept("tail -3 run.log", "loss=0.3") == ["`tail -3 run.log`:\nloss=0.3"]


def test_tool_output_redacts_and_cleans_what_it_keeps():
    output = ("Error: token sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxx refused\n<private>Error: my PIN</private>\n"
              "\x1b[31mFAILED\x1b[0m a.py\nprogress 1%\rprogress 100%\n")  # fmt: skip
    (text,) = kept("OPENROUTER_API_KEY=xxxxxxxxxxxxxxxx ./run", output)
    assert text == (
        "`OPENROUTER_API_KEY=[redacted] ./run`:\nError: token [redacted] refused\nFAILED a.py\nprogress 100%"
    )
    key = "-----BEGIN RSA PRIVATE KEY-----\n" + "EXAMPLE\n" * 5 + "-----END RSA PRIVATE KEY-----"
    assert "EXAMPLE" not in "".join(kept("deploy", f"{key}\nError", error=True))


def test_tool_output_caps():
    (text,) = kept("run", "\n".join(f"loss={i}.{'0' * 300}" for i in range(50)))  # the end of each result, in its room
    assert len(text) <= claude_code.ACTION_CHARS
    assert text.startswith("`run`:\n…\n") and text.endswith(" …")  # and each line cut
    assert "loss=49." in text and "loss=0." not in text
    base = {"sessionId": "s", "cwd": "/w", "timestamp": "2026-10-12T10:00:00Z"}
    busy = [{**base, "type": "user", "uuid": "p", "message": {"content": "go"}}]
    for i in range(30):  # 30 commands in a turn, each with 500 characters to keep: the newest ones stay
        busy += tool_run(f"run-{i}", "\n".join(f"loss={i}.{n}" for n in range(60)))
        busy[-2]["uuid"], busy[-1]["uuid"] = f"c{i}", f"r{i}"
        busy[-2]["message"]["content"][0]["id"] = busy[-1]["message"]["content"][0]["tool_use_id"] = f"t{i}"
    items = claude_code.items_from_lines(enumerate(busy), tool_output=True)
    tools = [it for it in items if it["author"] == "tool"]
    assert sum(len(it["text"]) for it in tools) <= claude_code.TOOL_TURN_CHARS
    assert tools[-1]["text"].startswith("`run-29`") and len(tools) < 30
    # the next prompt has a turn of its own
    busy += [{**base, "type": "user", "uuid": "p2", "message": {"content": "again"}}, *tool_run("run-new", "loss=1")]
    tools = [it["text"] for it in claude_code.items_from_lines(enumerate(busy), tool_output=True) if it["author"] == "tool"]
    assert tools[-1] == "`run-new`:\nloss=1" and tools[-2].startswith("`run-29`")
    # what failed stays even when it is older than the rest
    busy[1]["message"]["content"][0]["is_error"] = busy[2]["message"]["content"][0]["is_error"] = True
    tools = [it["text"] for it in claude_code.items_from_lines(enumerate(busy), tool_output=True) if it["author"] == "tool"]
    assert tools[0].startswith("`run-0` (failed):") and tools[-2].startswith("`run-29`")


def test_tool_output_is_captured_once_and_can_be_turned_off(tmp_path, mem, monkeypatch):
    path = write_jsonl(tmp_path / "proj" / "sess-t.jsonl", claude_code_tool_work())
    state = tmp_path / "state"
    assert claude_code.capture_transcript(mem, path, state, "sess-t") == {"added": 11, "duplicate": 0}  # 5 + 2 actions + 4
    assert claude_code.capture_transcript(mem, path, tmp_path / "lost", "sess-t") == {"added": 0, "duplicate": 11}
    assert mem.flush(30)  # only two hold these words: the other two come from embeddings, done in the background
    found = query(mem, "passed pytest", filter={"author": "tool"}, top_k=10, max_tokens=2000)["items"]
    assert len(found) == 4
    monkeypatch.setenv("COGITO_MEM_CAPTURE_TOOL_OUTPUT", "off")
    other = write_jsonl(tmp_path / "proj" / "sess-u.jsonl", claude_code_tool_work("sess-u"))
    assert claude_code.capture_transcript(mem, other, state, "sess-u") == {"added": 7, "duplicate": 0}
    # with both off: the messages alone
    monkeypatch.setenv("COGITO_MEM_CAPTURE_ACTIONS", "off")
    last = write_jsonl(tmp_path / "proj" / "sess-v.jsonl", claude_code_tool_work("sess-v"))
    assert claude_code.capture_transcript(mem, last, state, "sess-v") == {"added": 5, "duplicate": 0}


# --------------------------------------------------------------------------- reading past sessions


def session_start(root, monkeypatch, capsys, hook: dict | str | None = None) -> tuple[list, str]:
    """Run the ``SessionStart`` hook with no real background process. Returns what it would start, and its stdout."""
    from cogito_mem.cli import main

    started: list = []
    monkeypatch.setattr("cogito_mem.cli._detach", lambda argv, _root: started.append(argv))
    body = hook if isinstance(hook, str) else json.dumps(hook or {"hook_event_name": "SessionStart", "session_id": "now", "cwd": "/work/app"})
    monkeypatch.setattr("sys.stdin", io.StringIO(body))
    assert main(["--root", str(root), "recall", "claude-code"]) == 0
    return started, capsys.readouterr().out


@pytest.fixture
def sweep_env(isolated_env, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_BACKFILL", "on")
    monkeypatch.setenv("COGITO_MEM_URL", "http://127.0.0.1:9")  # nothing listens there, and no service is started
    return isolated_env


def test_first_session_start_reads_past_sessions_in_the_background(tmp_path, sweep_env, monkeypatch, capsys):
    root = tmp_path / "cogito-home"
    started, out = session_start(root, monkeypatch, capsys)
    assert started == [["capture", "claude-code", "--all", "--namespace", "ksirg-hollow", "--root", str(root)]]
    payload = json.loads(out)["hookSpecificOutput"]
    assert payload["hookEventName"] == "SessionStart"
    assert "past Claude Code sessions" in payload["additionalContext"] and "COGITO_MEM_BACKFILL=on" in payload["additionalContext"]
    assert claude_code.last_sweep(root) is not None
    # once: the next session says nothing, and starts nothing while the sweep is recent
    assert session_start(root, monkeypatch, capsys) == ([], "")
    # later it looks again, for what no hook saw, and says nothing
    marker = root / claude_code.SWEEP_MARKER
    long_ago = time.time() - claude_code.SWEEP_SECONDS - 1
    os.utime(marker, (long_ago, long_ago))
    started, out = session_start(root, monkeypatch, capsys)
    assert len(started) == 1 and out == ""
    assert marker.stat().st_mtime > long_ago + 1


def test_past_sessions_notice_comes_with_the_last_session(tmp_path, sweep_env, monkeypatch, capsys):
    projects = sweep_env / ".claude" / "projects"
    write_jsonl(projects / "-work-app" / "old.jsonl", claude_code_transcript("old", "2026-10-01"))
    hook = {"hook_event_name": "SessionStart", "session_id": "now", "cwd": "/work/app",
            "transcript_path": str(projects / "-work-app" / "now.jsonl")}  # fmt: skip
    _, out = session_start(tmp_path / "h", monkeypatch, capsys, hook)
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("cogito-mem is reading") and "the last session in this project (old," in context


def test_past_sessions_are_left_alone_when_switched_off(tmp_path, sweep_env, monkeypatch, capsys):
    root = tmp_path / "cogito-home"
    monkeypatch.delenv("COGITO_MEM_BACKFILL")  # asked for, never assumed
    assert session_start(root, monkeypatch, capsys) == ([], "")
    monkeypatch.setenv("COGITO_MEM_BACKFILL", "on")
    monkeypatch.setenv("COGITO_MEM_CAPTURE", "off")
    assert session_start(root, monkeypatch, capsys) == ([], "")
    monkeypatch.delenv("COGITO_MEM_CAPTURE")
    assert claude_code.last_sweep(root) is None
    monkeypatch.setenv("COGITO_MEM_RECALL", "off")  # recall off adds nothing to the conversation; the sweep is its own switch
    started, out = session_start(root, monkeypatch, capsys)
    assert len(started) == 1 and out == ""


def test_past_sessions_only_on_session_start(tmp_path, sweep_env, monkeypatch, capsys):
    root = tmp_path / "cogito-home"
    prompt = {"hook_event_name": "UserPromptSubmit", "session_id": "now", "cwd": "/work/app", "prompt": "yes"}
    for hook in (prompt, "garbage", "[1, 2]", ""):
        assert session_start(root, monkeypatch, capsys, hook) == ([], "")
    assert claude_code.last_sweep(root) is None


def test_a_sweep_that_cannot_start_never_fails_the_session(tmp_path, sweep_env, monkeypatch, capsys):
    from cogito_mem.cli import main

    def cannot(*_):
        raise OSError("no room")

    root = tmp_path / "cogito-home"
    monkeypatch.setattr("cogito_mem.cli._detach", cannot)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart"})))
    assert main(["--root", str(root), "recall", "claude-code"]) == 0
    assert capsys.readouterr().out == ""
    assert claude_code.last_sweep(root) is None  # the next session tries again
    assert "reading past sessions): OSError: no room" in (root / "run" / "recall.log").read_text()


@pytest.fixture
def live_service(isolated_env, monkeypatch):
    from cogito_mem.server import MemoryServer

    memory = Memory(None, embedder="hash")
    server = MemoryServer(memory, host="127.0.0.1", port=0)
    threading.Thread(target=server.serve, daemon=True).start()
    monkeypatch.setenv("COGITO_MEM_URL", server.url)
    monkeypatch.setenv("COGITO_MEM_NAMESPACE", "default")
    yield memory
    server.shutdown()
    memory.close()


def test_backfill_also_reads_what_the_hooks_left_out(tmp_path, live_service, monkeypatch, capsys):
    from cogito_mem.cli import main

    root = tmp_path / "cogito-home"
    project = tmp_path / "home" / ".claude" / "projects" / "-work-app"
    path = write_jsonl(project / "sess-t.jsonl", claude_code_tool_work())
    write_jsonl(project / "sess-t" / "subagents" / "agent-a1.jsonl", claude_code_subagent("a1", "sess-t"))
    sdk = claude_code_tool_work("sess-sdk")  # an Agent SDK run: same folder, and no hook ever saw it
    write_jsonl(project / "sess-sdk.jsonl", [{**r, "entrypoint": "sdk-py"} for r in sdk])
    # a hook of an earlier version read the session: its cursor stands at the end, with less kept
    monkeypatch.setenv("COGITO_MEM_CAPTURE_TOOL_OUTPUT", "off")
    monkeypatch.setenv("COGITO_MEM_CAPTURE_SUBAGENTS", "off")
    main(["--root", str(root), "capture", "claude-code", "--transcript", str(path), "--session", "sess-t", "--wait"])
    assert json.loads(capsys.readouterr().out) == {"added": 7, "duplicate": 0}
    monkeypatch.delenv("COGITO_MEM_CAPTURE_TOOL_OUTPUT")
    monkeypatch.delenv("COGITO_MEM_CAPTURE_SUBAGENTS")

    assert main(["--root", str(root), "capture", "claude-code", "--all"]) == 0
    totals = json.loads(capsys.readouterr().out)
    assert totals == {"added": 16, "duplicate": 7, "files": 2}  # sess-t: 4 tool items, 1 report; the SDK run whole
    assert claude_code.last_sweep(root) is not None
    assert main(["--root", str(root), "capture", "claude-code", "--all"]) == 0
    assert json.loads(capsys.readouterr().out) == {"added": 0, "duplicate": 0, "files": 2}


@pytest.mark.slow
def test_session_start_really_reads_past_sessions_in_the_background(tmp_path, live_service, monkeypatch, capsys):
    monkeypatch.setenv("COGITO_MEM_BACKFILL", "on")
    from cogito_mem.cli import main

    monkeypatch.setenv("PYTHONPATH", SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    root = tmp_path / "cogito-home"
    projects = root.parent / "home" / ".claude" / "projects"
    write_jsonl(projects / "-work-app" / "sess-a.jsonl", claude_code_transcript("sess-a", "2026-09-01"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart"})))
    assert main(["--root", str(root), "recall", "claude-code"]) == 0
    assert "cogito-mem is reading" in capsys.readouterr().out
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        items = query(live_service, "storage layer", max_tokens=1000, namespace="default")["items"]
        if items:
            break
        time.sleep(0.1)
    assert {i["thread_id"] for i in items} == {"sess-a"}, (root / "run" / "capture.log").read_text()


def test_doctor_says_whether_past_sessions_were_read(tmp_path, isolated_env, monkeypatch):
    from cogito_mem.doctor import doctor

    monkeypatch.setenv("COGITO_MEM_URL", "http://127.0.0.1:9")
    root = tmp_path / "cogito-home"
    (isolated_env / ".claude.json").write_text("{}")
    lines: list[str] = []
    doctor(root, say=lines.append)
    assert any("past sessions not read" in line for line in lines)
    claude_code.mark_swept(root)
    lines.clear()
    doctor(root, say=lines.append)
    assert any("past sessions read in the background" in line for line in lines)


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


def test_shows_files_sees_past_prefixes_and_wrappers():
    from cogito_mem.capture.claude_code import shows_files

    for command in ("cat .env", "cd app && cat .env", "FOO=1 sudo cat /etc/hosts", "echo hi; head -3 secrets.txt", "/bin/cat x",
                    "git -C app diff HEAD", "tail -5 config.yaml", "ssh box 'cat .env'", "ssh -p 22 box cat .env", "env", "cat .env | grep KEY"):
        assert shows_files(command), command
    for command in ("pytest -q", "python train.py | tail -5", "make test && python eval.py", "tail -5 run/train.log",
                    "ssh box 'tail -5 run/train.log'", "cd app && pytest"):
        assert not shows_files(command), command


def test_redact_names_headers_and_url_params():
    assert redact("OPENROUTER_API_KEY:abcdefgh12345678") == "OPENROUTER_API_KEY:[redacted]"
    assert redact("GH_TOKEN=abcdefgh12345678 run") == "GH_TOKEN=[redacted] run"
    assert redact("DB_PASSWORD=hunter2hunter2") == "DB_PASSWORD=[redacted]"
    assert redact("Cookie: session=abcdefgh") == "Cookie: [redacted]"
    assert redact("see https://x.io/a?access_token=abc123&page=2") == "see https://x.io/a?access_token=[redacted]&page=2"
    assert redact("max_tokens: 5000 and top_k=10") == "max_tokens: 5000 and top_k=10"
