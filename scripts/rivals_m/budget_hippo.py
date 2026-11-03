#!/usr/bin/env python3
"""`hippo recall --budget N` on LongMemEval_M: its real output at each budget, a fresh store per question.

    python budget_hippo.py --hippo <clone>/bin/hippo.js --data-dir <split> --work <dir> --out rows.jsonl --workers 8

Builds each store the way hippo_run.py does and asks `hippo recall "<question>" --json --budget N` on a fresh copy for
N = 1000, 2500, 5000. hippo counts its own tokens (characters / 4) and always keeps its first result even when that is over
budget, so the scorer measures every reply with the shared counter and cuts at N. Only each result's content is kept.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hippo_run import REMEMBERED, hippo, when  # noqa: E402

BUDGETS = (1000, 2500, 5000)


def run_question(bin_path: str, data_dir: Path, work: Path, row: dict) -> dict:
    q = json.loads((data_dir / "q" / row["file"]).read_text(encoding="utf-8"))[0]
    qid = q["question_id"]
    root = work / qid
    if root.exists():
        shutil.rmtree(root)
    inst = root / "store"
    for sub in ("work", "global", "home"):
        (inst / sub).mkdir(parents=True)
    t0 = time.perf_counter()
    out = hippo(bin_path, inst, ["init", "--no-hooks", "--no-schedule", "--no-learn"])
    if str(inst / "work" / ".hippo") not in out:
        raise RuntimeError(f"{qid}: store did not land in its own folder: {out.strip()[:300]}")
    sids = q["haystack_session_ids"]
    ids: dict[str, str] = {}
    for i in sorted(range(len(sids)), key=lambda i: (when(q["haystack_dates"][i]), i)):
        text = "\n".join(turn["content"] for turn in q["haystack_sessions"][i])
        match = REMEMBERED.search(hippo(bin_path, inst, ["remember", "-"], stdin=text))
        if not match:
            raise RuntimeError(f"{qid}: no new memory id for session {sids[i]}")
        ids[match.group(1)] = sids[i]
    load_s = time.perf_counter() - t0
    replies = {}
    for n in BUDGETS:
        run = root / f"b{n}"
        shutil.copytree(inst, run)
        t1 = time.perf_counter()
        res = json.loads(hippo(bin_path, run, ["recall", q["question"], "--json", "--budget", str(n)]))
        ms = (time.perf_counter() - t1) * 1000
        shutil.rmtree(run)
        replies[str(n)] = {"passages": [{"s": ids[r["id"]], "t": r["content"]} for r in res["results"]], "query_ms": ms,
                           "hippo_tokens": sum(r["tokens"] for r in res["results"])}  # fmt: skip
    shutil.rmtree(root)
    return {"question_id": qid, "load_s": load_s, "replies": replies}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hippo", required=True)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--sample", default="all")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out", required=True)
    p.add_argument("--header", default="{}")
    args = p.parse_args()
    data_dir, work, out = Path(args.data_dir), Path(args.work), Path(args.out)
    work.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((data_dir / "manifest.json").read_text())
    selected = None if args.sample == "all" else set(manifest["samples"][args.sample])
    done: set[str] = set()
    if out.exists() and out.stat().st_size:
        lines = out.read_text().split("\n")
        if lines[0] != args.header:
            raise SystemExit(f"{out} holds other settings: {lines[0][:200]}")
        for line in lines[1:]:
            try:
                done.add(json.loads(line)["question_id"])
            except (ValueError, KeyError):
                pass
    else:
        out.write_text(args.header + "\n")
    todo = [r for r in manifest["rows"] if r["question_id"] not in done and (selected is None or r["question_id"] in selected)]
    lock = threading.Lock()
    start = time.perf_counter()
    count = [0]

    def job(row: dict) -> None:
        res = run_question(args.hippo, data_dir, work, row)
        with lock, open(out, "a", encoding="utf-8") as log:
            log.write(json.dumps(res) + "\n")
            count[0] += 1
            if count[0] % 10 == 0:
                print(f"{count[0]} questions, {time.perf_counter() - start:.0f} s", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fut in [pool.submit(job, row) for row in todo]:
            fut.result()
    print(f"done: {count[0]} questions run, {time.perf_counter() - start:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
