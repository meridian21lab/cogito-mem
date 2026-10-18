"""The two acceptance tests of requirements §3.5, run end to end as separate processes.

1. Setup: one command takes a clean HOME to a memory that answers a query through
   the MCP server exactly as Claude Code launches it, with no manual edits.
2. "A week ago": a scripted session holds an idea in passing, followed by a week of
   unrelated sessions, all captured by the Claude Code hook. One memory_query with the
   time window an assistant derives from "a week ago" finds the idea, and the returned
   item points to the original message.

Without network access these run with keyword search only. With
COGITO_MEM_TEST_LLAMA_SERVER and COGITO_MEM_TEST_MODEL set they use llama.cpp.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import LLAMA_MODEL, LLAMA_SERVER
from fixtures import write_jsonl

SRC = str(Path(__file__).resolve().parents[1] / "src")

pytestmark = pytest.mark.slow


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def machine(isolated_env, monkeypatch):
    """A clean machine: fake HOME, a free port, no downloads, and the service stopped afterwards."""
    monkeypatch.setenv("COGITO_MEM_PORT", str(free_port()))
    monkeypatch.setenv("COGITO_MEM_NO_DOWNLOAD", "1")
    monkeypatch.setenv("PYTHONPATH", SRC)
    if LLAMA_SERVER and LLAMA_MODEL:
        monkeypatch.setenv("COGITO_MEM_LLAMA_SERVER", LLAMA_SERVER)
        monkeypatch.setenv("COGITO_MEM_MODEL", LLAMA_MODEL)
    yield isolated_env
    subprocess.run([sys.executable, "-m", "cogito_mem", "stop"], capture_output=True, timeout=60)


def cogito(*args: str, timeout: float = 180) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "cogito_mem", *args], capture_output=True, text=True, timeout=timeout)


class McpSession:
    """Starts the MCP server with the command and args the client config holds."""

    def __init__(self, entry: dict, client_name: str = "claude-code"):
        self.proc = subprocess.Popen(
            [entry["command"], *entry["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )
        self.next_id = 0
        init = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": client_name, "version": "2.1"}})  # fmt: skip
        assert init["serverInfo"]["name"] == "cogito-mem"
        self.notify("notifications/initialized")

    def notify(self, method: str) -> None:
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict) -> dict:
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        reply = json.loads(self.proc.stdout.readline())
        assert reply["id"] == self.next_id, reply
        assert "error" not in reply, reply
        return reply["result"]

    def tool(self, name: str, **arguments) -> dict:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        assert result["isError"] is False, result
        return json.loads(result["content"][0]["text"])

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=30)


def test_setup_in_one_command(machine):
    home = machine
    out = cogito("install", "claude-code")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "service running" in out.stdout

    # Claude Code itself can start and reach the server
    if shutil.which("claude"):
        listed = subprocess.run(["claude", "mcp", "list"], capture_output=True, text=True, timeout=120, cwd=home)
        line = [x for x in listed.stdout.splitlines() if x.startswith("cogito-mem")]
        assert line and "Connected" in line[0], listed.stdout + listed.stderr

    # the first query, through the command Claude Code runs
    entry = json.loads((home / ".claude.json").read_text())["mcpServers"]["cogito-mem"]
    session = McpSession(entry)
    try:
        tools = session.request("tools/list", {})["tools"]
        assert {t["name"] for t in tools} == {"memory_append", "memory_query"}
        saved = session.tool("memory_append", text="Decision: we keep the memory local-first.")
        assert saved["items"][0]["status"] == "added"
        answer = session.tool("memory_query", text="what did we decide about local-first?")
        assert answer["items"][0]["text"] == "Decision: we keep the memory local-first."
        assert answer["items"][0]["author"] == "claude-code"
    finally:
        session.close()


def _session(sid: str, day: dt.datetime, turns: list[tuple[str, str]]) -> list[dict]:
    records = []
    for i, (role, text) in enumerate(turns):
        when = (day + dt.timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        records.append({"type": role, "uuid": f"{sid}-{i}", "sessionId": sid, "timestamp": when,
                         "isSidechain": False, "message": {"role": role, "content": text}})  # fmt: skip
    return records


IDEA = (
    "OK the test passes now. By the way, I have an idea: agents could subscribe to a thread and get "
    "new items pushed to them instead of polling. Anyway, back to the date parser."
)

WEEK = [
    [("user", "The date parser fails on offsets like +05:30."), ("assistant", "The regex drops the minutes; fixed."),
     ("user", IDEA), ("assistant", "Noted. The parser fix is merged.")],
    [("user", "Can you help me fill in the tax form?"), ("assistant", "Sure, start with section B.")],
    [("user", "Why does my CSS grid overflow on phones?"), ("assistant", "Use minmax(0, 1fr) for the columns.")],
    [("user", "Plan a weekend in Gdańsk."), ("assistant", "Saturday: the old town; Sunday: the beach.")],
    [("user", "Explain BM25 again."), ("assistant", "It scores term frequency against document length.")],
    [("user", "Great idea for dinner: pierogi with mushrooms."), ("assistant", "Here is a recipe.")],
    [("user", "Review this SQL migration."), ("assistant", "Add an index on created_at.")],
    [("user", "Summarise the meeting notes."), ("assistant", "Three decisions and two open questions.")],
]  # fmt: skip


def test_remember_an_idea_from_a_week_ago(machine):
    home = machine
    assert cogito("install", "claude-code").returncode == 0
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    hook = settings["hooks"]["Stop"][-1]["hooks"][0]["command"]
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    projects = home / ".claude" / "projects" / "-work-app"
    expected = 0
    for n, turns in enumerate(WEEK):  # day 0 is a week ago, then one session a day
        day = now - dt.timedelta(days=7) + dt.timedelta(days=n, hours=-2)
        sid = f"session-day-{n}"
        path = write_jsonl(projects / f"{sid}.jsonl", _session(sid, day, turns))
        hook_input = {"session_id": sid, "transcript_path": str(path), "cwd": "/work/app", "hook_event_name": "Stop"}
        done = subprocess.run(hook, shell=True, input=json.dumps(hook_input), text=True, timeout=30)
        assert done.returncode == 0
        expected += len(turns)

    # the hook hands the work to a background process; wait until everything is in
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = json.loads(cogito("status").stdout or "{}")
        if status.get("namespaces", {}).get("default", {}).get("messages", 0) >= expected:
            break
        time.sleep(0.2)
    else:
        pytest.fail(f"capture did not finish: {status}")

    # "Do you remember that idea from a week ago?" -> one query with a window around 7 days ago
    entry = json.loads((home / ".claude.json").read_text())["mcpServers"]["cogito-mem"]
    session = McpSession(entry)
    try:
        answer = session.tool(
            "memory_query",
            text="Do you remember that idea from a week ago?",
            valid_after=(now - dt.timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            valid_before=(now - dt.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    finally:
        session.close()
    hits = [i for i in answer["items"] if "subscribe to a thread" in i["text"]]
    assert hits, answer
    hit = hits[0]
    assert answer["items"].index(hit) == 0
    assert all("pierogi" not in i["text"] for i in answer["items"])  # outside the window
    # the item points to the original message: resending it returns the same id, and the span matches
    resent = json.loads(
        cogito("request", json.dumps({"op": "append", "items": [
            {"author": "user", "text": IDEA, "client_ref": "claude-code:session-day-0-2"}]})).stdout  # fmt: skip
    )["items"][0]
    assert resent["status"] == "duplicate" and resent["id"] == hit["source"]["id"]
    assert IDEA[hit["source"]["start"] : hit["source"]["end"]] == hit["text"]
    assert hit["thread_id"] == "session-day-0" and hit["author"] == "user"
    assert hit["valid_at"].startswith((now - dt.timedelta(days=7, hours=2)).strftime("%Y-%m-%d"))
