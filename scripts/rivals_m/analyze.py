#!/usr/bin/env python3
"""Cogi minus each rival, paired by question, with the interval and pass mark fixed before running.

    python analyze.py --cogi-src <worktree>/src --cogi m-recall-b904848.json --out comparison.json rival.json ...

Pass mark, set before any rival ran: Cogi leads or matches a rival if the lower end of the paired 95% bootstrap interval is
above -5 points. The bootstrap is `paired_bootstrap` from src/cogito_mem/evals/longmemeval.py, parsed from that file so it
can't drift: 10,000 resamples of questions, seed 0, percentile interval. Prints Markdown tables.
"""
from __future__ import annotations

import argparse
import ast
import json
import random
from pathlib import Path

PAIRED = ("recall_any@5", "recall_any@10", "recall_all@5")
SHOWN = ("recall_any@1", "recall_any@3", "recall_any@5", "recall_any@10", "recall_all@5", "recall_all@10", "ndcg@10", "mrr")
HEADS = ("R@1", "R@3", "R@5", "R@10", "all@5", "all@10", "NDCG@10", "MRR")
TYPES = ("single-session-user", "single-session-assistant", "single-session-preference", "multi-session",
         "temporal-reasoning", "knowledge-update")  # fmt: skip
PASS_MARK = -5.0


def load_bootstrap(src: Path):
    source = (src / "cogito_mem/evals/longmemeval.py").read_text(encoding="utf-8")
    keep = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "paired_bootstrap"]
    ns: dict = {"random": random}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "longmemeval.py", "exec"), ns)  # noqa: S102
    return ns["paired_bootstrap"]


def means(rows: list[dict]) -> dict:
    scored = [r["session"] for r in rows if r.get("session")]
    n = len(scored)
    out: dict = {"n": n}
    if not n:
        return out
    for k in SHOWN[:6]:
        out[k] = sum(s[k] for s in scored) / n
    out["ndcg@10"] = sum(s["ndcg@10"] for s in scored) / n
    out["mrr"] = sum(1 / s["rank"] for s in scored if s["rank"]) / n
    return out


def cells(m: dict) -> str:
    vals = [f"{100 * m[k]:.1f}" for k in SHOWN[:6]] + [f"{m['ndcg@10']:.3f}", f"{m['mrr']:.3f}"]
    return " | ".join(vals)


def compare(bootstrap, cogi: dict[str, dict], rival: dict[str, dict], ids: list[str]) -> dict:
    out: dict = {"questions": len(ids)}
    for metric in PAIRED:
        a = [float(rival[q]["session"][metric]) for q in ids]
        b = [float(cogi[q]["session"][metric]) for q in ids]
        mean, lo, hi = bootstrap(a, b, 10_000, 0)
        out[metric] = {
            "rival": round(100 * sum(a) / len(a), 2),
            "cogi": round(100 * sum(b) / len(b), 2),
            "cogi_minus_rival": round(100 * mean, 2),
            "ci95": [round(100 * lo, 2), round(100 * hi, 2)],
            "passes": 100 * lo > PASS_MARK,
            "cogi_only": sum(1 for x, y in zip(a, b) if y > x),
            "rival_only": sum(1 for x, y in zip(a, b) if x > y),
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cogi-src", required=True)
    p.add_argument("--cogi", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("rivals", nargs="+")
    args = p.parse_args()
    bootstrap = load_bootstrap(Path(args.cogi_src))
    cogi_file = json.loads(Path(args.cogi).read_text(encoding="utf-8"))
    cogi = {r["question_id"]: r for r in cogi_file["per_question"]}
    report: dict = {"cogi_file": args.cogi, "cogi_commit": cogi_file["meta"].get("commit"), "pass_mark_points": PASS_MARK,
                    "bootstrap": "paired_bootstrap, 10000 resamples of questions, seed 0", "rivals": {}}  # fmt: skip
    table = ["| System | Questions | n | " + " | ".join(HEADS) + " |", "|---|---|---:|" + "---:|" * len(HEADS)]
    table.append(f"| Cogi | all | {means(list(cogi.values()))['n']} | {cells(means(list(cogi.values())))} |")
    answerable = [r for r in cogi.values() if not r["abstention"]]
    table.append(f"| Cogi | answerable | {len(answerable)} | {cells(means(answerable))} |")
    paired = ["| Rival | Questions | n | Metric | Rival | Cogi | Cogi minus rival | 95% interval | Cogi only / rival only | Passes (lower end above -5) |",
              "|---|---|---:|---|---:|---:|---:|---|---:|---|"]  # fmt: skip
    types = ["| System | " + " | ".join(t for t in TYPES) + " |", "|---|" + "---:|" * len(TYPES)]
    per_type_cogi = {t: means([r for r in answerable if r["question_type"] == t]) for t in TYPES}
    types.append("| Cogi (R@5 / all@5) | " + " | ".join(f"{100 * per_type_cogi[t]['recall_any@5']:.1f} / {100 * per_type_cogi[t]['recall_all@5']:.1f}" for t in TYPES) + " |")
    for path in args.rivals:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        name = Path(path).stem
        if data["meta"]["dataset_sha256"] != cogi_file["meta"]["dataset_sha256"]:
            raise SystemExit(f"{path}: another dataset file than Cogi's")
        rival = {r["question_id"]: r for r in data["per_question"]}
        missing = set(rival) - set(cogi)
        if missing:
            raise SystemExit(f"{path}: {len(missing)} questions not in Cogi's file")
        ids_all = [q for q in cogi if q in rival]
        ids_ans = [q for q in ids_all if not cogi[q]["abstention"]]
        rows = [rival[q] for q in ids_all]
        ans_rows = [rival[q] for q in ids_ans]
        report["rivals"][name] = {
            "file": path,
            "all": means(rows),
            "answerable": means(ans_rows),
            "cogi_same_questions_all": means([cogi[q] for q in ids_all]),
            "cogi_same_questions_answerable": means([cogi[q] for q in ids_ans]),
            "paired_all": compare(bootstrap, cogi, rival, ids_all),
            "paired_answerable": compare(bootstrap, cogi, rival, ids_ans),
            "speed": {k: data["summary"].get(k) for k in ("load_s", "query_ms", "rss_mb_peak", "disk_mb")},
            "meta": data["meta"],
        }
        table.append(f"| {name} | all | {len(ids_all)} | {cells(means(rows))} |")
        table.append(f"| {name} | answerable | {len(ids_ans)} | {cells(means(ans_rows))} |")
        if len(ids_all) < len(cogi):
            table.append(f"| Cogi on {name}'s questions | all | {len(ids_all)} | {cells(means([cogi[q] for q in ids_all]))} |")
        for label, key in (("all", "paired_all"), ("answerable", "paired_answerable")):
            comp = report["rivals"][name][key]
            for metric in PAIRED:
                c = comp[metric]
                paired.append(f"| {name} | {label} | {comp['questions']} | {metric.replace('recall_any', 'R').replace('recall_all', 'all')} | "
                              f"{c['rival']:.1f} | {c['cogi']:.1f} | {c['cogi_minus_rival']:+.1f} | {c['ci95'][0]:+.1f} to {c['ci95'][1]:+.1f} | "
                              f"{c['cogi_only']} / {c['rival_only']} | {'yes' if c['passes'] else 'NO'} |")  # fmt: skip
        per_type = {t: means([r for r in ans_rows if r["question_type"] == t]) for t in TYPES}
        report["rivals"][name]["by_type"] = per_type
        types.append(f"| {name} | " + " | ".join(
            (f"{100 * per_type[t]['recall_any@5']:.1f} / {100 * per_type[t]['recall_all@5']:.1f}" if per_type[t]["n"] else "n/a") for t in TYPES) + " |")  # fmt: skip
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n".join(table))
    print()
    print("\n".join(paired))
    print()
    print("\n".join(types))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
