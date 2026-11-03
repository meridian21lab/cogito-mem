#!/usr/bin/env python3
"""Score a rival's ranked sessions with Cogi's own arithmetic, and write a result file that pairs with Cogi's.

    python score_rows.py --cogi-src <worktree>/src --data-dir <split> --rows rows.jsonl --out result.json \
        --meta '{"project": ...}' --expect-sample all

The scoring functions are taken from `src/cogito_mem/evals/longmemeval_recall.py` by parsing that file and running
only its scoring definitions, so nothing of Cogi is imported, no dependency is needed and the arithmetic can't drift.
Rows get the same fields as Cogi's, except `turn`, which is None: this comparison is at session level only.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import time
from collections import defaultdict
from pathlib import Path

RECALL_PATH = "cogito_mem/evals/longmemeval_recall.py"
WANTED = {"KS", "NDCG_K", "KEEP_RANKED", "TYPES", "SETS", "is_abstention", "distinct", "ndcg", "score", "level_metrics",
          "groups", "summarize", "table"}  # fmt: skip


def load_scoring(src: Path) -> tuple[dict, str]:
    source = (src / RECALL_PATH).read_text(encoding="utf-8")
    keep = []
    for node in ast.parse(source).body:
        names = [node.name] if isinstance(node, ast.FunctionDef) else []
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if WANTED & set(names):
            keep.append(node)
    ns: dict = {"math": math, "defaultdict": defaultdict, "__annotations__": {}}
    exec(compile("from __future__ import annotations\n", "scoring", "exec"), ns)  # noqa: S102
    exec(compile(ast.Module(body=keep, type_ignores=[]), RECALL_PATH, "exec"), ns)  # noqa: S102
    missing = WANTED - set(ns)
    if missing:
        raise SystemExit(f"{RECALL_PATH} no longer defines {sorted(missing)}")
    return ns, hashlib.sha256(source.encode()).hexdigest()


def read_rows(path: Path) -> tuple[dict, dict[str, dict]]:
    lines = path.read_text(encoding="utf-8").split("\n")
    head = json.loads(lines[0])
    rows: dict[str, dict] = {}
    for line in lines[1:]:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        rows[r["question_id"]] = r
    return head, rows


def machine() -> dict:
    def sysctl(name: str) -> str:
        return subprocess.run(["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True).stdout.strip()
    return {"hostname": platform.node(), "platform": platform.platform(), "chip": sysctl("machdep.cpu.brand_string"),
            "cpus": os.cpu_count(), "memory_gb": round(int(sysctl("hw.memsize") or 0) / 2**30)}  # fmt: skip


def spread(values: list[float]) -> dict:
    if not values:
        return {}
    v = sorted(values)
    return {"median": round(statistics.median(v), 3), "p95": round(v[int(0.95 * (len(v) - 1))], 3), "max": round(v[-1], 3)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cogi-src", required=True)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--rows", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--meta", default="{}")
    p.add_argument("--expect", type=int, help="fail if the rows don't hold this many questions")
    args = p.parse_args()
    ns, scoring_sha = load_scoring(Path(args.cogi_src))
    manifest = json.loads((Path(args.data_dir) / "manifest.json").read_text(encoding="utf-8"))
    head, done = read_rows(Path(args.rows))
    rows = []
    outside = 0
    for m in manifest["rows"]:
        r = done.get(m["question_id"])
        if r is None:
            continue
        present = set(m["haystack_session_ids"])
        named = m["answer_session_ids"]
        want = {s for s in named if s in present}
        ranked = ns["distinct"](r["ranked_sessions"])
        outside += sum(1 for s in ranked if s not in present)
        row = {
            "question_id": m["question_id"],
            "question_type": m["question_type"],
            "abstention": ns["is_abstention"](m["question_id"]),
            "sessions": len(present),
            "evidence_sessions": len(want),
            "evidence_sessions_missing": len(set(named) - present),
            "evidence_turns": 0,
            "items_returned": r.get("items_returned", len(ranked)),
            "sessions_ranked": len(ranked),
            "session": ns["score"](ranked, want) if want else None,
            "turn": None,
            "ranked_sessions": ranked[: ns["KEEP_RANKED"]],
            "load_s": round(r["load_s"], 3),
            "query_ms": round(r["query_ms"], 2),
            "rss_mb": round(r.get("rss_mb", 0), 1),
            "disk_mb": round(r.get("disk_mb", 0), 2),
        }
        for extra in ("returned_tokens", "candidates", "tier", "documents"):
            if extra in r:
                row[extra] = r[extra]
        rows.append(row)
    if args.expect is not None and len(rows) != args.expect:
        raise SystemExit(f"{args.rows}: {len(rows)} questions, expected {args.expect}")
    if outside:
        raise SystemExit(f"{args.rows}: {outside} ranked sessions aren't in their question's haystack")
    summary = ns["summarize"](rows)
    summary["load_s"].update(spread([r["load_s"] for r in rows]))
    summary["query_ms"].update(spread([r["query_ms"] for r in rows]))
    summary["rss_mb_peak"] = max(r["rss_mb"] for r in rows)
    summary["disk_mb"] = spread([r["disk_mb"] for r in rows])
    meta = {
        **json.loads(args.meta),
        **{k: v for k, v in head.get("settings", {}).items()},
        "dataset": manifest["dataset"],
        "dataset_sha256": manifest["dataset_sha256"],
        "scoring": {"source": f"src/{RECALL_PATH}", "sha256": scoring_sha, "metric_level": "session"},
        "machine": machine(),
        "scored_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows_file": str(args.rows),
        "as_of": "none",
        "wall_s": round(float(json.loads(args.meta).get("wall_s", 0)), 1),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"meta": meta, "summary": summary, "per_question": rows}, indent=2), encoding="utf-8")
    print(ns["table"](summary, meta))
    print(f"load median {summary['load_s']['median']} s p95 {summary['load_s']['p95']} s; "
          f"query median {summary['query_ms']['median']} ms p95 {summary['query_ms']['p95']} ms; "
          f"peak RSS {summary['rss_mb_peak']} MB; disk median {summary['disk_mb'].get('median')} MB")  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
