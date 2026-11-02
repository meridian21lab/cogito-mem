#!/usr/bin/env python3
"""Split a LongMemEval file into one small JSON per question, and fix the question samples.

    python prepare_data.py --data longmemeval_m_cleaned.json --sha256 9d79... --out <dir>

The file is too big for some projects' readers (a 2.7 GB string is over Node's limit), and each
question needs only its own haystack, so every adapter reads a `[question]` file from here. The
files keep the dataset's own fields and text. `manifest.json` holds what scoring needs, so scoring
never reads the sessions.

Samples, fixed before any rival is run:
- `sample100`: seed 7, stratified by question type, largest-remainder proportional shares.
- `pilot20`: the same draw with 20 places, so a pilot isn't the file's first 20, which are one easy type.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def stratified(rows: list[dict], total: int, seed: int) -> list[str]:
    """question ids, in file order: per type a seeded shuffle, sized by largest remainder."""
    by_type: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_type[r["question_type"]].append(r["question_id"])
    n = len(rows)
    shares = {t: total * len(ids) / n for t, ids in by_type.items()}
    places = {t: int(s) for t, s in shares.items()}
    for t in sorted(shares, key=lambda t: (-(shares[t] - places[t]), t))[: total - sum(places.values())]:
        places[t] += 1
    rng = random.Random(seed)
    picked: set[str] = set()
    for t in sorted(by_type):
        ids = sorted(by_type[t])
        rng.shuffle(ids)
        picked.update(ids[: places[t]])
    return [r["question_id"] for r in rows if r["question_id"] in picked]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    data = Path(args.data)
    digest = sha256_file(data)
    if digest != args.sha256:
        raise SystemExit(f"{data}: sha256 {digest}, expected {args.sha256}")
    out = Path(args.out)
    (out / "q").mkdir(parents=True, exist_ok=True)
    questions = json.loads(data.read_bytes())
    rows = []
    for i, q in enumerate(questions):
        name = f"{i:03d}.json"
        (out / "q" / name).write_text(json.dumps([q]), encoding="utf-8")
        rows.append({
            "file": name,
            "question_id": q["question_id"],
            "question_type": q.get("question_type"),
            "question_date": q.get("question_date"),
            "answer_session_ids": q.get("answer_session_ids") or [],
            "haystack_session_ids": q["haystack_session_ids"],
        })
    manifest = {
        "dataset": data.name,
        "dataset_sha256": digest,
        "questions": len(rows),
        "rows": rows,
        "samples": {"sample100": stratified(rows, 100, 7), "pilot20": stratified(rows, 20, 7)},
    }
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, ids in manifest["samples"].items():
        counts: dict[str, int] = defaultdict(int)
        by_id = {r["question_id"]: r["question_type"] for r in rows}
        for q in ids:
            counts[by_id[q]] += 1
        print(name, len(ids), dict(counts))
    print(f"{len(rows)} questions, sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
