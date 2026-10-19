"""Claude Code: read the session transcript (JSONL) after each turn.

The ``Stop`` and ``SessionEnd`` hooks run ``cogito-mem capture claude-code``, which
reads the hook's JSON from stdin and hands the work to a background process, so
the chat never waits for the memory.

Kept: the user's typed messages and the assistant's text replies. Left out: tool
calls and their output, thinking, sub-agent (sidechain) turns, slash-command
output and injected system reminders. ``client_ref`` is the transcript line's
``uuid``; ``thread_id`` is the session id; ``title`` is the project, the line's
``cwd`` (a Claude Code worktree, ``<repo>/.claude/worktrees/<name>``, counts as
its repository), so recall can prefer the current project.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from . import Cursor, Sink, jsonl, read_new_lines, redact, send

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
)
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_WORKTREE = re.compile(r"[\\/]\.claude[\\/]worktrees[\\/][^\\/]+.*$", re.S)


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


def items_from_lines(lines: Iterable[tuple[int, dict]], session_id: str | None = None) -> list[dict]:
    items = []
    for _, rec in lines:
        kind = rec.get("type")
        if kind not in ("user", "assistant") or rec.get("isSidechain") or rec.get("isMeta"):
            continue
        message = rec.get("message")
        if not isinstance(message, dict):
            continue
        text = _REMINDER.sub("", _text_of(message.get("content"))).strip()
        if not text or text.startswith(_SKIP_PREFIXES):
            continue
        uuid = rec.get("uuid")
        if not uuid:
            continue
        item = {
            "author": "user" if kind == "user" else "assistant",
            "thread_id": rec.get("sessionId") or session_id or "default",
            "text": redact(text),
            "client_ref": f"claude-code:{uuid}",
        }
        project = project_of(rec.get("cwd"))
        if project:
            item["title"] = project
        if isinstance(rec.get("timestamp"), str):
            item["valid_at"] = rec["timestamp"]
        items.append(item)
    return items


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
    items = items_from_lines(jsonl(lines), session)
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
