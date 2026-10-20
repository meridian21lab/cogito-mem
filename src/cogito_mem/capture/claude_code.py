"""Claude Code: read the session transcript (JSONL) after each turn.

The ``Stop`` and ``SessionEnd`` hooks run ``cogito-mem capture claude-code``, which
reads the hook's JSON from stdin and hands the work to a background process, so
the chat never waits for the memory.

Kept: the user's typed messages and the assistant's text replies, without what is
marked ``<private>…</private>``, and what the session did: one ``actions`` item for
each run of tool calls between two prompts, with the commands it ran (and which
failed or did not run) and the files it read, edited or wrote, such as
"Ran `pytest -q` (failed), `pytest -q`. Edited src/x.py. Read README.md."
(``COGITO_MEM_CAPTURE_ACTIONS=off`` leaves these out). Left out: tool output and
file contents, thinking, sub-agent (sidechain) turns, slash-command output,
injected system reminders and the summary Claude Code writes when it compacts a
session.

``client_ref`` is the transcript line's ``uuid`` (for an ``actions`` item, that of its
first tool call, so reading a turn again, whole or from its middle, adds no second
copy); ``thread_id`` is the session id; ``title`` is the project, the line's ``cwd``
(a Claude Code worktree, ``<repo>/.claude/worktrees/<name>``, counts as its
repository), so recall can prefer the current project.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from . import Cursor, Sink, enabled, jsonl, read_new_lines, redact, send, without_private

ACTIONS = "actions"  # the author of what a turn did
ACTION_CHARS = 800  # about one piece (``split.PIECE_TOKENS``), so a busy turn cannot fill a reply
COMMAND_CHARS = 80

_SKIP_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "Caveat: The messages below were generated",
    "[Request interrupted by user",
    "<user-prompt-submit-hook>",
    "This session is being continued from a previous conversation",  # a compaction summary
)
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_WORKTREE = re.compile(r"[\\/]\.claude[\\/]worktrees[\\/][^\\/]+.*$", re.S)
_VERBS = {"Read": "Read", "NotebookRead": "Read", "Edit": "Edited", "MultiEdit": "Edited", "NotebookEdit": "Edited",
          "Write": "Wrote"}  # fmt: skip
_NOT_RUN = ("<tool_use_error>", "The user doesn't want to", "[Request interrupted")
_EXIT_CODE = re.compile(r"Exit code (\d+)")


def projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "projects"


def project_of(cwd: object) -> str | None:
    """The project a working directory belongs to: the directory, or a worktree's repository."""
    if not isinstance(cwd, str) or not cwd.strip():
        return None
    cwd = cwd.rstrip("/\\") or cwd
    return _WORKTREE.sub("", cwd) or cwd


def project_folder(project: str) -> str:
    """The folder name Claude Code gives a project under ``~/.claude/projects``."""
    return re.sub(r"[^A-Za-z0-9]", "-", project)


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n\n".join(p for p in parts if p)
    return ""


def items_from_lines(
    lines: Iterable[tuple[int, dict]], session_id: str | None = None, actions: bool = False
) -> list[dict]:
    """The messages as items, in order; with ``actions``, also one item per turn for its tool calls."""
    items = []
    turns: list[tuple[dict, dict]] = []  # (actions item, its tool calls by id)
    calls: dict | None = None  # the tool calls of the turn under way
    for _, rec in lines:
        kind = rec.get("type")
        if kind not in ("user", "assistant") or any(rec.get(k) for k in ("isSidechain", "isMeta", "isCompactSummary")):
            continue
        message = rec.get("message")
        if not isinstance(message, dict):
            continue
        text = without_private(_REMINDER.sub("", _text_of(message.get("content")))).strip()
        if text and not text.startswith(_SKIP_PREFIXES) and rec.get("uuid"):
            author = "user" if kind == "user" else "assistant"
            items.append(_item(rec, author, redact(text), f"claude-code:{rec['uuid']}", session_id))
        if not actions:
            continue
        content = message.get("content")
        blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
        if kind == "user" and not any(b.get("type") == "tool_result" for b in blocks):
            calls = None  # a prompt: the turn's actions end here
        for block in blocks:
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                if calls is None:
                    if not rec.get("uuid"):
                        continue
                    calls = {}
                    turns.append((_item(rec, ACTIONS, "", f"claude-code:{rec['uuid']}:actions", session_id), calls))
                    items.append(turns[-1][0])
                call = {"name": block.get("name"), "input": block["input"], "cwd": rec.get("cwd")}
                calls[block.get("id") or len(calls)] = call
            elif block.get("type") == "tool_result" and calls is not None and block.get("tool_use_id") in calls:
                calls[block["tool_use_id"]]["outcome"] = _outcome(block)
    for item, turn in turns:
        item["text"] = _summary(list(turn.values()))
    return [it for it in items if it["text"]]


def _item(rec: dict, author: str, text: str, client_ref: str, session_id: str | None) -> dict:
    item = {
        "author": author,
        "thread_id": rec.get("sessionId") or session_id or "default",
        "text": text,
        "client_ref": client_ref,
    }
    project = project_of(rec.get("cwd"))
    if project:
        item["title"] = project
    if isinstance(rec.get("timestamp"), str):
        item["valid_at"] = rec["timestamp"]
    return item


def _outcome(result: dict) -> str | None:
    """``failed``, ``not run`` (refused or interrupted), or None for a call that went through."""
    text = _text_of(result.get("content")).lstrip()
    if text.startswith(_NOT_RUN):
        return "not run"
    code = _EXIT_CODE.match(text)
    if result.get("is_error") or (code and code.group(1) != "0"):
        return "failed"
    return None


def _summary(calls: list[dict]) -> str:
    """One sentence per kind of action: the commands in order, then the files by what was done to them."""
    commands: list[str] = []
    files: dict[str, list[str]] = {}
    for call in calls:
        args, outcome = call["input"], call.get("outcome")
        cwd = call["cwd"] if isinstance(call["cwd"], str) else ""
        if call["name"] == "Bash" and isinstance(args.get("command"), str) and args["command"].strip():
            entry = f"`{_command(args['command'], cwd)}`" + (f" ({outcome})" if outcome else "")
            if entry not in commands:
                commands.append(entry)
            continue
        path = args.get("file_path") or args.get("notebook_path")
        if not isinstance(path, str) or not path.strip() or outcome:  # a failed edit changed nothing
            continue
        paths = files.setdefault(_VERBS.get(call["name"]) or f"Used {call['name']} on", [])
        if _relative(path, cwd) not in paths:
            paths.append(_relative(path, cwd))
    changed = {p for verb, paths in files.items() if verb != "Read" for p in paths}
    if "Read" in files:  # files are read before they are edited: that says nothing more
        files["Read"] = [p for p in files["Read"] if p not in changed]
    kinds = [("Ran", commands), *sorted(files.items(), key=lambda kv: kv[0] == "Read")]
    parts = [(verb, entries) for verb, entries in kinds if entries]
    # Each kind gets an equal share of the room, and what a short one leaves goes to the others.
    texts = [""] * len(parts)
    room = ACTION_CHARS
    by_length = sorted(range(len(parts)), key=lambda i: sum(len(e) + 2 for e in parts[i][1]))
    for left, i in zip(range(len(parts), 0, -1), by_length):
        texts[i] = _listing(*parts[i], room // left)
        room -= len(texts[i]) + 1
    text = redact(" ".join(texts))
    return text if len(text) <= ACTION_CHARS else text[: ACTION_CHARS - 2] + " …"


def _listing(verb: str, entries: list[str], room: int) -> str:
    """``Verb a, b, c.`` with as many entries as fit in ``room`` characters, and how many more there were."""
    text = verb
    for n, entry in enumerate(entries):
        if n and len(text) + len(entry) + (3 if n == len(entries) - 1 else 18) > room:
            return f"{text}, and {len(entries) - n} more."
        text += (", " if n else " ") + entry
    return text + "."


def _command(command: str, cwd: str) -> str:
    """The command's first line, cut to ``COMMAND_CHARS``, with paths under ``cwd`` relative to it."""
    command = redact(command.strip())  # before it is cut, so no part of a secret is left
    base = re.escape(cwd.rstrip("/\\"))
    if base:
        command = re.sub(rf"^cd +([\"']?){base}[/\\]?\1 *(?:&&|;) *", "", command)
        command = re.sub(rf"(?<![^\s\"'=:(]){base}[/\\]", "", command)
    first, *rest = command.splitlines() or [""]
    if rest or len(first) > COMMAND_CHARS:
        first = first[:COMMAND_CHARS].rstrip() + " …"
    return first


def _relative(path: str, cwd: str) -> str:
    base = cwd.rstrip("/\\")
    if base and path.startswith(base) and path[len(base) : len(base) + 1] in ("/", "\\"):
        return path[len(base) + 1 :]
    return path


def capture_transcript(
    sink: Sink,
    transcript: Path,
    state_dir: Path,
    session_id: str | None = None,
    namespace: str = "default",
    import_: bool = False,
) -> dict:
    """Append the new messages of one transcript. Returns counts of added and duplicate items."""
    session = session_id or transcript.stem
    cursor = Cursor(state_dir / "claude-code" / f"{_safe(session)}.json")
    lines, offset, line = read_new_lines(transcript, cursor.offset, cursor.line)
    items = items_from_lines(jsonl(lines), session, actions=enabled("COGITO_MEM_CAPTURE_ACTIONS"))
    if import_:
        items = [it for it in items if "valid_at" in it]
    counts = send(sink, items, namespace, import_) if items else {"added": 0, "duplicate": 0}
    cursor.save(offset, line)
    return counts


def capture_all(sink: Sink, state_dir: Path, namespace: str = "default", root: Path | None = None) -> dict:
    """Backfill every transcript under ~/.claude/projects (as history, with ``import``)."""
    total = {"added": 0, "duplicate": 0, "files": 0}
    base = root or projects_dir()
    if not base.is_dir():
        return total
    for path in sorted(base.glob("*/*.jsonl")):
        counts = capture_transcript(sink, path, state_dir, path.stem, namespace, import_=True)
        total["added"] += counts["added"]
        total["duplicate"] += counts["duplicate"]
        total["files"] += 1
    return total


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:128]
