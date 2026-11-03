#!/usr/bin/env python3
"""Prints the note's tables from results/rivals-m/comparison.json, so each number comes from a result file.

    python note_tables.py <results/rivals-m> <Cogi result>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LABELS = {
    "agentmemory-bm25": "agentmemory, default (BM25)",
    "agentmemory-hybrid": "agentmemory, older hybrid script",
    "deja-default": "deja-vu, default",
    "mempalace-raw": "MemPalace, default (raw)",
    "mempalace-hybrid_v4": "MemPalace, hybrid_v4",
    "hippo-default": "hippo, default recall (4,000-token budget)",
    "hippo-lifted": "hippo, recall with budget lifted",
    "hippo-best_dense_only": "hippo scripts, dense_only",
    "hippo-best_turn_sym": "hippo scripts, turn_sym",
    "hippo-best_turn_asym": "hippo scripts, turn_asym",
    "hippo-best_session_sym": "hippo scripts, session_sym",
    "hippo-best_session_asym": "hippo scripts, session_asym",
}
ORDER = list(LABELS)
SHOWN = ("recall_any@1", "recall_any@3", "recall_any@5", "recall_any@10", "recall_all@5", "recall_all@10")


def row(m: dict) -> str:
    return " | ".join(f"{100 * m[k]:.1f}" for k in SHOWN) + f" | {m['ndcg@10']:.3f} | {m['mrr']:.3f}"


def main() -> int:
    root, cogi_path = Path(sys.argv[1]), Path(sys.argv[2])
    c = json.loads((root / "comparison.json").read_text())
    rivals = {name.replace("-data_m-all", ""): v for name, v in c["rivals"].items()}
    first = next(iter(rivals.values()))
    head = "| System | R@1 | R@3 | R@5 | R@10 | all@5 | all@10 | NDCG@10 | MRR |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|"
    for key, cogi_key, title in (("all", "cogi_same_questions_all", "All 500"), ("answerable", "cogi_same_questions_answerable", "The 470 answerable")):
        print(f"\n**{title}**\n\n{head}")
        print(f"| **Cogi** | {row(first[cogi_key])} |")
        for name in ORDER:
            print(f"| {LABELS[name]} | {row(rivals[name][key])} |")
    for key, title in (("paired_all", "All 500"), ("paired_answerable", "The 470 answerable")):
        print(f"\n**{title}**: points, Cogi minus rival [95% interval]\n")
        print("| Rival setting | R@5 | R@10 | all@5 | Passes on all three |\n|---|---|---|---|---|")
        for name in ORDER:
            p = rivals[name][key]
            cell = lambda m: f"{p[m]['cogi_minus_rival']:+.1f} [{p[m]['ci95'][0]:+.1f}, {p[m]['ci95'][1]:+.1f}]"  # noqa: E731
            ok = all(p[m]["passes"] for m in ("recall_any@5", "recall_any@10", "recall_all@5"))
            print(f"| {LABELS[name]} | {cell('recall_any@5')} | {cell('recall_any@10')} | {cell('recall_all@5')} | {'yes' if ok else 'NO'} |")
    types = list(first["by_type"])
    print("\n**R@5 / all@5 by question type, answerable only**\n")
    cogi = {r["question_id"]: r for r in json.loads(cogi_path.read_text())["per_question"]}
    print("| System | " + " | ".join(f"{t} ({first['by_type'][t]['n']})" for t in types) + " |\n|---|" + "---:|" * len(types))
    cells = []
    for t in types:
        rs = [r["session"] for r in cogi.values() if r["question_type"] == t and not r["abstention"]]
        cells.append(f"{100 * sum(s['recall_any@5'] for s in rs) / len(rs):.1f} / {100 * sum(s['recall_all@5'] for s in rs) / len(rs):.1f}")
    print("| **Cogi** | " + " | ".join(cells) + " |")
    for name in ORDER:
        by = rivals[name]["by_type"]
        print(f"| {LABELS[name]} | " + " | ".join(f"{100 * by[t]['recall_any@5']:.1f} / {100 * by[t]['recall_all@5']:.1f}" for t in types) + " |")
    print("\n**Head-to-head counts, all 500**: questions only Cogi gets / only the rival gets\n")
    print("| Rival setting | R@5 | R@10 | all@5 |\n|---|---:|---:|---:|")
    for name in ORDER:
        p = rivals[name]["paired_all"]
        print(f"| {LABELS[name]} | " + " | ".join(f"{p[m]['cogi_only']} / {p[m]['rival_only']}" for m in ("recall_any@5", "recall_any@10", "recall_all@5")) + " |")
    print("\n**Speed and footprint**\n")
    print("| Setting | Load per question, median / p95 s | Query, median / p95 ms | Peak RSS MB | Disk per question MB | Wall s |\n|---|---:|---:|---:|---:|---:|")
    for name in ORDER:
        s, m = rivals[name]["speed"], rivals[name]["meta"]
        print(f"| {LABELS[name]} | {s['load_s']['median']} / {s['load_s']['p95']} | {s['query_ms']['median']} / {s['query_ms']['p95']} | {s['rss_mb_peak']:.0f} | {s['disk_mb']['median']} | {m.get('wall_s')} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
