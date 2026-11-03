#!/usr/bin/env python3
"""Distinct sessions and turns per split: what hippo's turn-level benchmark scripts would have to embed.

    python count_turns.py <split> ...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    for arg in sys.argv[1:]:
        data = Path(arg)
        manifest = json.loads((data / "manifest.json").read_text())
        sessions: set[str] = set()
        turns = 0
        chars = 0
        for row in manifest["rows"]:
            q = json.loads((data / "q" / row["file"]).read_text())[0]
            for sid, session in zip(q["haystack_session_ids"], q["haystack_sessions"]):
                if sid not in sessions:
                    sessions.add(sid)
                    turns += len(session)
                    chars += sum(len(t["content"]) for t in session)
        print(json.dumps({"split": data.name, "distinct_sessions": len(sessions), "distinct_turns": turns, "chars_over_4": chars // 4}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
