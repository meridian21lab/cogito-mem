"""Codex CLI: read the session files Codex writes under ``$CODEX_HOME/sessions``.

Codex runs the ``notify`` program after each turn; ``cogito-mem capture codex`` then
sweeps the session files changed recently and appends their new messages. The
payload Codex passes is not needed, so a change in its shape cannot break capture.

Kept: the user's messages and the agent's replies (``event_msg`` records of type
``user_message`` and ``agent_message``; older files without them fall back to
``response_item`` messages, minus injected environment and instruction blocks),
without what is marked ``<private>…</private>``.
``client_ref`` is ``<session id>:<line number>``; ``thread_id`` is the session id.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Iterable

from . import Cursor, Sink, jsonl, read_new_lines, redact, send, without_private

_INJECTED = ("<environment_context>", "<user_instructions>", "# AGENTS.md", "<permissions instructions>")


def codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    return Path(env).expanduser() if env else Path.home() / ".codex"


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text")
        ]
        return "\n\n".join(p for p in parts if p)
    return ""


def session_id_of(records: Iterable[tuple[int, dict]], fallback: str) -> str:
    for _, rec in records:
        if rec.get("type") == "session_meta" and isinstance(rec.get("payload"), dict):
            sid = rec["payload"].get("id")
            if sid:
                return str(sid)
        if "id" in rec and "timestamp" in rec and "type" not in rec:  # pre-2025-09 first line
            return str(rec["id"])
    return fallback


def items_from_records(records: list[tuple[int, dict]], session_id: str, use_events: bool) -> list[dict]:
    """``use_events``: the file has ``event_msg`` records (files from 2025-09 on start with ``session_meta``)."""
    items = []
    for n, rec in records:
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else rec
        text = ""
        author = None
        if use_events:
            if rec.get("type") != "event_msg":
                continue
            if payload.get("type") == "user_message":
                author, text = "user", payload.get("message") or ""
            elif payload.get("type") == "agent_message":
                author, text = "assistant", payload.get("message") or ""
        else:
            if payload.get("type") != "message" or payload.get("role") not in ("user", "assistant"):
                continue
            author = payload["role"]
            text = _content_text(payload.get("content"))
            if author == "user" and text.lstrip().startswith(_INJECTED):
                continue
        text = without_private(text) if isinstance(text, str) else ""
        if not author or not text.strip():
            continue
        item = {
            "author": author,
            "thread_id": session_id,
            "text": redact(text.strip()),
            "client_ref": f"codex:{session_id}:{n}",
        }
        if isinstance(rec.get("timestamp"), str):
            item["valid_at"] = rec["timestamp"]
        items.append(item)
    return items


def capture_file(sink: Sink, path: Path, state_dir: Path, namespace: str = "default", import_: bool = False) -> dict:
    key = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:20]
    cursor = Cursor(state_dir / "codex" / f"{key}.json")
    with open(path, "rb") as fh:
        head = fh.readline().decode("utf-8", "replace")
    first = list(jsonl([(0, head)]))
    session = session_id_of(first, path.stem)
    use_events = bool(first) and first[0][1].get("type") == "session_meta"
    lines, offset, line = read_new_lines(path, cursor.offset, cursor.line)
    items = items_from_records(list(jsonl(lines)), session, use_events)
    if import_:
        items = [it for it in items if "valid_at" in it]
    counts = send(sink, items, namespace, import_) if items else {"added": 0, "duplicate": 0}
    cursor.save(offset, line)
    return counts


def sweep(
    sink: Sink,
    state_dir: Path,
    namespace: str = "default",
    since_days: float | None = 2.0,
    import_: bool = False,
    home: Path | None = None,
) -> dict:
    """Capture every session file changed in the last ``since_days`` days (all of them if None)."""
    total = {"added": 0, "duplicate": 0, "files": 0}
    base = (home or codex_home()) / "sessions"
    if not base.is_dir():
        return total
    cutoff = None if since_days is None else time.time() - since_days * 86400
    for path in sorted(base.rglob("rollout-*.jsonl")):
        if cutoff is not None and path.stat().st_mtime < cutoff:
            continue
        counts = capture_file(sink, path, state_dir, namespace, import_)
        total["added"] += counts["added"]
        total["duplicate"] += counts["duplicate"]
        total["files"] += 1
    return total
