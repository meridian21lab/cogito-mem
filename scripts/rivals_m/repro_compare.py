#!/usr/bin/env python3
"""Does each adapter reproduce its project's published LongMemEval-S result? Compares with the receipts in its own repo.

    python repro_compare.py <rivals-m> <repro-s result folder>

- agentmemory: docs/benchmarks/receipts/2026-10-28/longmemeval/scores.ndjson.gz, strict recall per question.
- MemPalace: benchmarks/results_mempal_raw_session_20260414_1629.jsonl, its ranked sessions per question.
- hippo: docs/evals/2026-09-28-recall-cli-longmemeval-raw.json, rank of the first answer session per question,
  measured on hippo 1.52.5 (the run here is 3.1.0).
- deja-vu: docs/benchmarks/longmemeval-s-full.json, totals only, so no per-question check is possible.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path


def rows(result: Path) -> dict[str, dict]:
    return {r["question_id"]: r for r in json.loads(result.read_text())["per_question"]}


def pct(values) -> float:
    values = list(values)
    return 100 * sum(values) / len(values)


def main() -> int:
    base, out = Path(sys.argv[1]), Path(sys.argv[2])
    report: dict = {}

    mine = rows(out / "agentmemory-bm25-data_s-all.json")
    path = base / "agentmemory/repo/docs/benchmarks/receipts/2026-10-28/longmemeval/scores.ndjson.gz"
    scores = [json.loads(x) for x in gzip.open(path, "rt")]
    bm25 = {s["questionId"]: s for s in scores if "bm25" in s.get("adapter", "")}
    ans = [q for q in bm25 if bm25[q].get("recallAllAtK") is not None]
    report["agentmemory-bm25"] = {
        "questions": len(ans),
        "published_all@5": round(pct(float(bm25[q]["recallAllAtK"]) for q in ans), 1),
        "ours_all@5": round(pct(mine[q]["session"]["recall_all@5"] for q in ans), 1),
        "same_outcome": sum(float(bm25[q]["recallAllAtK"]) == float(mine[q]["session"]["recall_all@5"]) for q in ans),
    }

    mine = rows(out / "mempalace-raw-data_s-all.json")
    path = base / "mempalace/repo/benchmarks/results_mempal_raw_session_20260414_1629.jsonl"
    manifest = json.loads((base / "data_s/manifest.json").read_text())
    answers = {r["question_id"]: set(r["answer_session_ids"]) for r in manifest["rows"]}
    same_top5, same_hit, hits_pub = 0, 0, 0
    pub = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for r in pub:
        top = list(dict.fromkeys(x["corpus_id"] for x in r["retrieval_results"]["ranked_items"]))[:5]
        hit = bool(set(top) & answers[r["question_id"]])
        hits_pub += hit
        same_hit += hit == mine[r["question_id"]]["session"]["recall_any@5"]
        same_top5 += top == mine[r["question_id"]]["ranked_sessions"][:5]
    report["mempalace-raw"] = {
        "questions": len(pub),
        "published_R@5": round(100 * hits_pub / len(pub), 1),
        "ours_R@5": round(pct(r["session"]["recall_any@5"] for r in mine.values()), 1),
        "same_outcome": same_hit,
        "same_top5_order": same_top5,
    }

    mine = rows(out / "deja-default-data_s-all.json")
    total = json.loads((base / "dejavu/repo/docs/benchmarks/longmemeval-s-full.json").read_text())["total"]
    report["deja-default"] = {
        "questions": total["n"],
        "published": {k: round(total[k], 1) for k in ("hit@1", "hit@5", "hit@10")},
        "ours": {f"hit@{k}": round(pct(r["session"][f"recall_any@{k}"] for r in mine.values()), 1) for k in (1, 5, 10)},
        "mrr": {"published": round(total["mrr"], 3),
                "ours": round(sum(1 / r["session"]["rank"] for r in mine.values() if r["session"]["rank"]) / len(mine), 3)},
    }  # fmt: skip

    raw = json.loads((base / "hippo/repo/docs/evals/2026-09-28-recall-cli-longmemeval-raw.json").read_text())
    columns = raw["per_question_columns"]
    table = {row[0]: dict(zip(columns, row)) for row in raw["per_question"]}
    for run, name in (("A-default", "hippo-default"), ("A-lifted", "hippo-lifted")):
        mine = rows(out / f"{name}-data_s-sample100.json")
        ranks = {q: table[q][f"{run}.first_answer_rank"] for q in mine}
        hit = {q: ranks[q] is not None and ranks[q] <= 5 for q in mine}
        report[name] = {
            "questions": len(mine),
            "published_R@5_on_these": round(pct(hit.values()), 1),
            "ours_R@5": round(pct(r["session"]["recall_any@5"] for r in mine.values()), 1),
            "same_outcome": sum(hit[q] == mine[q]["session"]["recall_any@5"] for q in mine),
            "same_first_rank": sum(ranks[q] == mine[q]["session"]["rank"] for q in mine if run == "A-lifted") if run == "A-lifted" else None,
        }
    # MemPalace's no-LLM best: its published 98.4 is on the 450 held-out questions of its own split.
    path = base / "mempalace/repo/benchmarks/results_mempal_hybrid_v4_held_out_session_20260414_1634.jsonl"
    mine = rows(out / "mempalace-hybrid_v4-data_s-all.json")
    pub = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    hits, same = 0, 0
    for r in pub:
        top = list(dict.fromkeys(x["corpus_id"].rsplit("_turn_", 1)[0] for x in r["retrieval_results"]["ranked_items"]))[:5]
        hit = bool(set(top) & answers[r["question_id"]])
        hits += hit
        same += hit == mine[r["question_id"]]["session"]["recall_any@5"]
    report["mempalace-hybrid_v4"] = {
        "questions": len(pub),
        "published_R@5": round(100 * hits / len(pub), 1),
        "ours_R@5_same_questions": round(pct(mine[r["question_id"]]["session"]["recall_any@5"] for r in pub), 1),
        "same_outcome": same,
    }

    # agentmemory's older hybrid: benchmark/LONGMEMEVAL.md, any-hit over all 500, an older input pipeline.
    mine = rows(out / "agentmemory-hybrid-data_s-all.json")
    report["agentmemory-hybrid"] = {
        "questions": len(mine),
        "published": {"R@5": 95.2, "R@10": 98.6, "NDCG@10": 0.879, "MRR": 0.882},
        "ours": {"R@5": round(pct(r["session"]["recall_any@5"] for r in mine.values()), 1),
                 "R@10": round(pct(r["session"]["recall_any@10"] for r in mine.values()), 1),
                 "NDCG@10": round(sum(r["session"]["ndcg@10"] for r in mine.values()) / len(mine), 3),
                 "MRR": round(sum(1 / r["session"]["rank"] for r in mine.values() if r["session"]["rank"]) / len(mine), 3)},
    }  # fmt: skip

    # hippo's five benchmark-script settings: docs/evals/2026-09-23-longmemeval-reproduction.md, "Today's build".
    published = {"dense_only": (85.4, 96.8, 98.8), "turn_sym": (90.0, 97.8, 99.6), "turn_asym": (87.0, 97.8, 98.8),
                 "session_sym": (88.4, 98.0, 99.4), "session_asym": (87.4, 98.0, 99.0)}  # fmt: skip
    report["hippo-best"] = {}
    for name, (r1, r5, r10) in published.items():
        mine = rows(out / f"hippo-best_{name}-data_s-all.json")
        report["hippo-best"][name] = {
            "published_R@1,5,10": [r1, r5, r10],
            "ours_R@1,5,10": [round(pct(r["session"][f"recall_any@{k}"] for r in mine.values()), 1) for k in (1, 5, 10)],
        }
    print(json.dumps(report, indent=2))
    (out / "repro-comparison.json").write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
