#!/usr/bin/env python3
"""`hippo recall` on one LongMemEval split, built and asked through its CLI, a fresh store per question.

    python hippo_run.py --hippo <clone>/bin/hippo.js --data-dir <split> --work <dir> --sample all --workers 8 \
        --out-default default.jsonl --out-lifted lifted.jsonl --header '{...}'

Follows benchmarks/longmemeval/recall_cli_haystack.py at the pinned commit: `hippo init --no-hooks --no-schedule
--no-learn`, one `hippo remember -` per session in date order holding the turn contents joined by newlines, then
`hippo recall "<question>" --json` on a fresh copy of the store, once at the default budget and once with
`--budget 100000000`. Every call runs with cwd, HIPPO_HOME and HOME inside the question's own folder. What this script
changes: it reads a per-question file, keeps the whole ranking rather than the top 10, finishes a question at a time
so it can resume, and removes the question's store once it has been measured (500 stores would hold many GB).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import resource
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

PASS_ENV = {"PATH", "TMPDIR", "LANG"}
REMEMBERED = re.compile(r"^Remembered \[([^\]]+)\]", re.M)
LIFTED = "100000000"


def when(stamp: str) -> datetime:
    day, _weekday, clock = stamp.split(" ")  # "2023/05/20 (Sat) 02:21"
    return datetime.strptime(f"{day} {clock}", "%Y/%m/%d %H:%M")


def hippo(bin_path: str, inst: Path, args: list[str], stdin: str | None = None) -> str:
    home = str(inst / "home")
    env = {k: v for k, v in os.environ.items() if k in PASS_ENV}
    env.update(HIPPO_HOME=str(inst / "global"), HOME=home, USERPROFILE=home)
    proc = subprocess.run(
        ["node", bin_path, *args], cwd=inst / "work", env=env, input=stdin,
        stdin=None if stdin is not None else subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", timeout=900,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"hippo {args[0]} exited {proc.returncode}: {proc.stderr.strip()[:400]}")
    return proc.stdout


def dir_mb(root: Path) -> float:
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) / (1 << 20)


def recall(bin_path: str, src: Path, run: Path, question: str, ids: dict[str, str], flags: list[str]) -> dict:
    shutil.copytree(src, run)  # recall strengthens what it returns and writes traces
    t0 = time.perf_counter()
    out = json.loads(hippo(bin_path, run, ["recall", question, "--json", *flags]))
    query_ms = (time.perf_counter() - t0) * 1000
    shutil.rmtree(run)
    results = out["results"]
    unknown = [r["id"] for r in results if r["id"] not in ids]
    if unknown:
        raise RuntimeError(f"recall returned ids the side file doesn't hold: {unknown[:3]}")
    return {
        "ranked_sessions": [ids[r["id"]] for r in results],
        "items_returned": len(results),
        "returned_tokens": sum(r["tokens"] for r in results),
        "candidates": (out.get("suppressionSummary") or {}).get("totalCandidates"),
        "query_ms": query_ms,
    }


def run_question(bin_path: str, data_dir: Path, work: Path, row: dict) -> tuple[dict, dict]:
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
    order = sorted(range(len(sids)), key=lambda i: (when(q["haystack_dates"][i]), i))
    ids: dict[str, str] = {}
    for i in order:
        text = "\n".join(turn["content"] for turn in q["haystack_sessions"][i])
        match = REMEMBERED.search(hippo(bin_path, inst, ["remember", "-"], stdin=text))
        if not match or match.group(1) in ids:
            raise RuntimeError(f"{qid}: no new memory id for session {sids[i]}")
        ids[match.group(1)] = sids[i]
    load_s = time.perf_counter() - t0
    disk = dir_mb(inst / "work" / ".hippo")
    default = recall(bin_path, inst, root / "default", q["question"], ids, [])
    lifted = recall(bin_path, inst, root / "lifted", q["question"], ids, ["--budget", LIFTED])
    shutil.rmtree(root)
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / (1 << 20)
    common = {"question_id": qid, "load_s": load_s, "disk_mb": disk, "rss_mb": rss}
    return {**common, **default}, {**common, **lifted}


def read_done(path: Path, header: str) -> set[str]:
    done: set[str] = set()
    if not path.exists() or not path.stat().st_size:
        path.write_text(header + "\n", encoding="utf-8")
        return done
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines[0] != header:
        raise SystemExit(f"{path} holds a run with other settings: {lines[0]}")
    for line in lines[1:]:
        try:
            done.add(json.loads(line)["question_id"])
        except (ValueError, KeyError):
            pass
    return done


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hippo", required=True)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--sample", default="all")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out-default", required=True)
    p.add_argument("--out-lifted", required=True)
    p.add_argument("--header", default="{}")
    args = p.parse_args()
    data_dir, work = Path(args.data_dir), Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    selected = None if args.sample == "all" else set(manifest["samples"][args.sample])
    out_d, out_l = Path(args.out_default), Path(args.out_lifted)
    done = read_done(out_d, args.header) & read_done(out_l, args.header)
    todo = [r for r in manifest["rows"] if r["question_id"] not in done
            and (selected is None or r["question_id"] in selected)]
    lock = threading.Lock()
    start = time.perf_counter()
    count = [0]

    def job(row: dict) -> None:
        d, l = run_question(args.hippo, data_dir, work, row)
        with lock, open(out_d, "a", encoding="utf-8") as fd, open(out_l, "a", encoding="utf-8") as fl:
            fd.write(json.dumps(d) + "\n")
            fl.write(json.dumps(l) + "\n")
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
