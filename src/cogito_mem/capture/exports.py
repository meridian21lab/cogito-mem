"""Past chats from claude.ai and ChatGPT, loaded from each app's data export.

Both exports hold a ``conversations.json`` (inside the .zip they are sent as).
Messages are appended with ``import: true``, so they keep the time they were said,
and with the message id as ``client_ref``, so importing the same export twice adds
nothing. ``thread_id`` is the conversation id and ``title`` the conversation name.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from .. import timeutil
from . import Sink, redact, send


def load_conversations(path: Path) -> Any:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == "conversations.json"]
            if not names:
                raise ValueError(f"{path} has no conversations.json")
            with zf.open(names[0]) as fh:
                return json.load(fh)
    if path.is_dir():
        path = path / "conversations.json"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _iso(value: Any) -> str | None:
    if isinstance(value, (int, float)) and value > 0:
        return timeutil.format(timeutil.from_epoch_seconds(float(value)))
    if isinstance(value, str) and value:
        try:
            return timeutil.format(timeutil.parse(value))
        except ValueError:
            return None
    return None


def claude_items(conversations: list[dict]) -> list[dict]:
    """claude.ai export: conversations with ``chat_messages`` (sender ``human`` / ``assistant``)."""
    items = []
    for conv in conversations:
        thread = conv.get("uuid") or "default"
        title = conv.get("name") or None
        conv_time = _iso(conv.get("created_at"))
        for msg in conv.get("chat_messages") or []:
            text = msg.get("text") or ""
            if not text.strip() and isinstance(msg.get("content"), list):
                text = "\n\n".join(
                    b.get("text", "") for b in msg["content"] if isinstance(b, dict) and b.get("type") == "text"
                )
            when = _iso(msg.get("created_at")) or conv_time
            if not text.strip() or not when or not msg.get("uuid"):
                continue
            items.append(
                {
                    "author": "user" if msg.get("sender") == "human" else "assistant",
                    "thread_id": thread,
                    "title": title,
                    "valid_at": when,
                    "text": redact(text.strip()),
                    "client_ref": f"claude-ai:{msg['uuid']}",
                }
            )
    return items


def _chatgpt_branch(conv: dict) -> list[dict]:
    """The messages on the conversation's shown branch, oldest first."""
    mapping = conv.get("mapping") or {}
    node_id = conv.get("current_node")
    chain = []
    seen = set()
    while node_id and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        node = mapping[node_id]
        if node.get("message"):
            chain.append(node["message"])
        node_id = node.get("parent")
    if not chain and mapping:  # no current_node: fall back to time order
        chain = [n["message"] for n in mapping.values() if n.get("message")]
        chain.sort(key=lambda m: m.get("create_time") or 0)
        return chain
    return list(reversed(chain))


def chatgpt_items(conversations: list[dict]) -> list[dict]:
    """ChatGPT export: conversations with a ``mapping`` tree of messages."""
    items = []
    for conv in conversations:
        thread = conv.get("conversation_id") or conv.get("id") or "default"
        title = conv.get("title") or None
        conv_time = _iso(conv.get("create_time"))
        for msg in _chatgpt_branch(conv):
            role = (msg.get("author") or {}).get("role")
            if role not in ("user", "assistant"):
                continue
            meta = msg.get("metadata") or {}
            if meta.get("is_visually_hidden_from_conversation"):
                continue
            content = msg.get("content") or {}
            if content.get("content_type") not in ("text", "multimodal_text"):
                continue
            text = "\n\n".join(p for p in content.get("parts") or [] if isinstance(p, str) and p.strip())
            when = _iso(msg.get("create_time")) or conv_time
            if not text.strip() or not when or not msg.get("id"):
                continue
            items.append(
                {
                    "author": role,
                    "thread_id": thread,
                    "title": title,
                    "valid_at": when,
                    "text": redact(text.strip()),
                    "client_ref": f"chatgpt:{msg['id']}",
                }
            )
    return items


def import_export(sink: Sink, kind: str, path: Path, namespace: str = "default") -> dict:
    conversations = load_conversations(path)
    if not isinstance(conversations, list):
        raise ValueError("conversations.json should hold a list of conversations")
    if kind == "claude":
        items = claude_items(conversations)
    elif kind == "chatgpt":
        items = chatgpt_items(conversations)
    else:
        raise ValueError(f"unknown export kind {kind!r}")
    counts = send(sink, items, namespace, import_=True)
    counts["conversations"] = len(conversations)
    return counts
