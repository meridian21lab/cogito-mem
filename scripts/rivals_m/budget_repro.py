#!/usr/bin/env python3
"""Does the scored Cogi row reproduce the one in the notes? Compares question by question with m-final.json.

    python budget_repro.py <scored cogi.json> <m-final.json>

Source of the notes' 56.4 / 70.0 / 81.1: summary.all.search.base.none.coverage in results/long-history/m-final.json (and m-full.json),
answerable with labels, n = 470, no date cutoff, commit 59ce22d. Exit 1 if it doesn't match.
"""
from __future__ import annotations

import json
import sys

BUDGETS = ("1000", "2500", "5000")


def main() -> int:
    ours = json.load(open(sys.argv[1]))
    old = json.load(open(sys.argv[2]))
    published = old["summary"]["all"]["search"]["base"]["none"]["coverage"]
    print("source meta: commit", old["meta"]["commit"], "n", old["summary"]["answerable_with_labels"], "dataset", old["meta"]["dataset_sha256"][:12])
    print("published coverage, answerable, no cutoff:", {b: published[b] for b in BUDGETS})
    print("ours by message id, answerable:           ", ours["coverage_by_id"]["answerable"])
    print("ours by text rule, answerable:            ", {b: ours["summary"]["answerable"][b]["coverage"] for b in BUDGETS}, "n", ours["summary"]["answerable"]["n"])
    print("ours by message id, all labelled:         ", ours["coverage_by_id"]["labelled"], "n", ours["summary"]["labelled"]["n"])
    print("ours by text rule, all labelled:          ", {b: ours["summary"]["labelled"][b]["coverage"] for b in BUDGETS})
    print("whole message, all labelled:              ", {b: ours["summary"]["labelled"][b]["whole"] for b in BUDGETS})
    print("text rule vs id, questions agreeing:", ours["meta"]["rule_text_vs_id_agreement"])
    rows = {r["question_id"]: r for r in old["per_question"]}
    ok = True
    for b in BUDGETS:
        same, diff, n = 0, [], 0
        for r in ours["per_question"]:
            old_row = rows[r["question_id"]]
            if old_row["abstention"] or not old_row["evidence_turns"]:
                continue
            n += 1
            mine = r["budgets"][b]["by_id"]
            theirs = old_row["search"]["base"]["none"]["budgets"][b]["all"]
            if mine == theirs:
                same += 1
            else:
                diff.append(r["question_id"])
        print(f"budget {b}: {same}/{n} questions agree by id with the file; differ {diff[:8]}")
        ok = ok and round(ours["coverage_by_id"]["answerable"][b], 4) == round(published[b], 4)
    bad = [r["question_id"] for r in ours["per_question"] if bool(r["evidence"]) != bool(r["evidence_ids"])]
    print("questions where the two evidence definitions disagree on having any:", bad[:8], len(bad))
    dup = [r["question_id"] for r in ours["per_question"] if r["evidence"] != r["evidence_ids"]]
    print("questions whose distinct evidence texts differ from Cogi's evidence id count:", len(dup), dup[:8])
    print("MATCH" if ok else "NO MATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
