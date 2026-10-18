"""Capture chats into the memory as you go (requirements §3.5).

Each source turns its chat files into append items with a stable ``client_ref``,
so sending a message twice changes nothing. Live capture appends normally (the
memory learns of a message when it is captured); backfilling old files uses
``import`` so ``as_of`` sees them as if the memory had been running then.

Obvious secrets (API keys, tokens, private keys) are replaced with ``[redacted]``
before anything is stored, because the memory never forgets.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Protocol

BATCH = 200

_SECRETS = [
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
]
_ASSIGNED = re.compile(
    r"(?i)\b((?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|password|passwd|client[_-]?secret)"
    r"[\"']?\s*[:=]\s*[\"']?)([^\s\"']{8,})"
)

REDACTED = "[redacted]"


def redact(text: str) -> str:
    for pattern in _SECRETS:
        text = pattern.sub(REDACTED, text)
    return _ASSIGNED.sub(lambda m: m.group(1) + REDACTED, text)


class Sink(Protocol):
    def handle(self, body: dict) -> dict: ...


def send(sink: Sink, items: list[dict], namespace: str = "default", import_: bool = False) -> dict:
    """Append items in batches. Returns counts of added and duplicate items."""
    counts = {"added": 0, "duplicate": 0}
    if import_:
        items = sorted(items, key=lambda it: it["valid_at"])
    for i in range(0, len(items), BATCH):
        body = {"op": "append", "namespace": namespace, "import": import_, "items": items[i : i + BATCH]}
        for result in sink.handle(body)["items"]:
            counts[result["status"]] += 1
    return counts


class Cursor:
    """How far into a chat file capture has read: a byte offset and the line number there."""

    def __init__(self, path: Path):
        self.path = path
        try:
            state = json.loads(path.read_text())
            self.offset, self.line = int(state["offset"]), int(state["line"])
        except (OSError, ValueError, KeyError, TypeError):
            self.offset, self.line = 0, 0

    def save(self, offset: int, line: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"offset": offset, "line": line}))
        tmp.replace(self.path)
        self.offset, self.line = offset, line


def read_new_lines(path: Path, offset: int = 0, line: int = 0) -> tuple[list[tuple[int, str]], int, int]:
    """Complete lines after byte ``offset`` as (line number, text), plus the new offset and line.

    Line numbers count from the start of the file, so they are stable ids for a line.
    """
    size = path.stat().st_size
    if offset > size:  # the file was replaced
        offset, line = 0, 0
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    end = data.rfind(b"\n") + 1
    if end == 0:
        return [], offset, line
    raw_lines = data[:end].split(b"\n")[:-1]
    out = [(line + i, raw.decode("utf-8", "replace")) for i, raw in enumerate(raw_lines)]
    return out, offset + end, line + len(raw_lines)


def jsonl(lines: Iterable[tuple[int, str]]) -> Iterable[tuple[int, dict]]:
    for n, line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield n, obj
