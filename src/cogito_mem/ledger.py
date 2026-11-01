"""The ledger: what the memory put in front of Claude, and what Claude did with it.

One JSON line per event in ``run/ledger.jsonl``: each hook call (fired or not, or withheld for the holdout, with
the ids and the tokens) and each ``memory_query`` and ``memory_open`` call. It holds ids and counts, never text.
Writing never gets in the way of a prompt.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from . import timeutil

NAME = "ledger.jsonl"
MAX_BYTES = 64 * 1024 * 1024


def record(folder: Path | None, event: dict) -> None:
    if folder is None:
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / NAME
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.replace(folder / (NAME + ".1"))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": timeutil.format(timeutil.now_ms()), **event}) + "\n")
    except OSError:
        pass


def read(folder: Path, since_ms: int | None = None) -> list[dict]:
    rows: list[dict] = []
    for path in (folder / (NAME + ".1"), folder / NAME):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                if since_ms is None or timeutil.parse(row["at"]) >= since_ms:
                    rows.append(row)
            except (ValueError, KeyError):
                continue
    return rows


def summarize(rows: list[dict]) -> dict:
    """Injections, their cost, and how many of the lines shown were then opened in that session."""
    prompts = [r for r in rows if r.get("event") == "UserPromptSubmit"]
    fired = [r for r in rows if r.get("fired") and not r.get("withheld") and r.get("event") != "open"]
    shown: dict[object, set[str]] = defaultdict(set)
    for r in fired:
        shown[r.get("session")].update(r.get("items") or [])
    opens = [r for r in rows if r.get("event") == "open"]
    opened_shown = sum(
        1 for r in opens if any(str(i).endswith(str(r.get("id"))) for i in shown.get(r.get("session"), ()))
    )
    return {
        "events": len(rows),
        "sessions": len({r.get("session") for r in rows if r.get("session")}),
        "prompts": len(prompts),
        "prompts_fired": sum(1 for r in prompts if r.get("fired")),
        "withheld": sum(1 for r in rows if r.get("withheld")),
        "by_event": dict(Counter(r.get("event") for r in fired)),
        "tokens_injected": sum(int(r.get("tokens") or 0) for r in fired),
        "tokens_per_injection": round(sum(int(r.get("tokens") or 0) for r in fired) / len(fired), 1) if fired else 0,
        "lines_shown": sum(len(r.get("items") or []) for r in fired),
        "opens": len(opens),
        "opens_of_lines_shown": opened_shown,
        "searches": sum(1 for r in rows if r.get("event") == "query"),
        "hook_ms_median": sorted(int(r.get("ms") or 0) for r in prompts)[len(prompts) // 2] if prompts else None,
    }
