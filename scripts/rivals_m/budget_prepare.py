#!/usr/bin/env python3
"""Readies raw budget rows for scoring: merges MemPalace's shards and splits hippo's scripts into one file per setting.

    python budget_prepare.py <rivals-m>/rows/budget
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1])
    for tag in ("all", "sample100"):
        shards = sorted(root.glob(f"mempalace-mine-data_m-{tag}.jsonl.shard*"))
        if shards:
            head, rows = None, {}
            for s in shards:
                lines = s.read_text().split("\n")
                head = head or lines[0]
                for line in lines[1:]:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    rows[r["question_id"]] = line
            (root / f"mempalace-mine-data_m-{tag}.jsonl").write_text(head + "\n" + "\n".join(rows.values()) + "\n")
            print(f"mempalace-mine {tag}: {len(rows)} questions from {len(shards)} shards")
    src = root / "hippo-scripts-data_m-all.jsonl"
    if src.exists():
        lines = src.read_text().split("\n")
        outs: dict[str, list[str]] = {}
        for line in lines[1:]:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            for name, ranked in r["settings"].items():
                outs.setdefault(name, []).append(json.dumps({"question_id": r["question_id"], "ranked": ranked, "query_ms": r["query_ms"]}))
        for name, rows_out in outs.items():
            (root / f"hippo-scripts_{name}-data_m-all.jsonl").write_text(lines[0] + "\n" + "\n".join(rows_out) + "\n")
            print(f"hippo scripts {name}: {len(rows_out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
