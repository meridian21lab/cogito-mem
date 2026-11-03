#!/usr/bin/env python3
"""Checks that a rival's low score isn't a silent failure, and gathers the footprint numbers.

    python validate.py <results folder> <rivals-m> <Cogi result>
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def main() -> int:
    results, base, cogi_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    manifest = json.loads((base / "data_m/manifest.json").read_text())
    print("haystack sessions per question: median", statistics.median(len(r["haystack_session_ids"]) for r in manifest["rows"]))
    cogi = json.loads(cogi_path.read_text())
    s = cogi["summary"]
    print("Cogi", {k: s.get(k) for k in ("load_s", "query_ms")}, "sessions ranked median",
          statistics.median(r["sessions_ranked"] for r in cogi["per_question"]),
          "wall_s", cogi["meta"].get("wall_s"), "items median", statistics.median(r["items_returned"] for r in cogi["per_question"]))  # fmt: skip
    for path in sorted(results.glob("*-data_m-*.json")):
        d = json.loads(path.read_text())
        rows = d["per_question"]
        ranked = [r["sessions_ranked"] for r in rows]
        print(f"{path.stem}: n={len(rows)} wall_s={d['meta'].get('wall_s')} sessions_ranked median {statistics.median(ranked)} "
              f"min {min(ranked)} max {max(ranked)}; under 5 ranked: {sum(x < 5 for x in ranked)}; "
              f"under 10: {sum(x < 10 for x in ranked)}; never found: {sum(1 for r in rows if r['session'] and r['session']['rank'] is None)}")  # fmt: skip
        print("   load", d["summary"]["load_s"], "query", d["summary"]["query_ms"], "rss peak", d["summary"]["rss_mb_peak"],
              "first-question rss", rows[0]["rss_mb"], "disk", d["summary"]["disk_mb"])  # fmt: skip
        for extra in ("candidates", "returned_tokens", "documents"):
            vals = [r[extra] for r in rows if r.get(extra) is not None]
            if vals:
                print(f"   {extra}: median {statistics.median(vals)} max {max(vals)}; at 200: {sum(v == 200 for v in vals)}")
        if "tier" in rows[0]:
            tiers: dict[str, int] = {}
            for r in rows:
                tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
            print("   tiers", tiers)
    answer_word = sum("answer" in json.loads((base / "data_m/q" / r["file"]).read_text())[0]["question"].lower() for r in manifest["rows"])
    print("questions holding the word 'answer' (session ids in M can start answer_):", answer_word)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
