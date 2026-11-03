#!/usr/bin/env python3
"""MemPalace on one LongMemEval split, a question at a time, through its own benchmark's retrieval functions.

    python mempalace_run.py --repo <clone> --data-dir <split> --sample all --mode raw --out rows.jsonl --header '{...}'

`--mode raw` calls `build_palace_and_retrieve`, the setting behind its 96.6; `--mode hybrid_v4` calls
`build_palace_and_retrieve_hybrid_v4`, the no-LLM setting behind its 98.4, with the benchmark's default weight.
Both come from benchmarks/longmemeval_bench.py, imported unchanged. What this script adds: it reads a per-question
file, keeps only the first `n_results` of each ranking (the benchmark appends the unretrieved corpus in file order
after them, which isn't a ranking), and times Chroma's add apart from the rest. Scoring happens elsewhere.
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path


class TimedCollection:
    """Counts the time spent in collection.add, which embeds and stores every document."""

    spent = 0.0

    def __init__(self, inner):
        self._inner = inner

    def add(self, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            return self._inner.add(*args, **kwargs)
        finally:
            TimedCollection.spent += time.perf_counter() - t0

    def __getattr__(self, name):
        return getattr(self._inner, name)


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
        except (ValueError, KeyError):  # empty, or cut short by an interruption
            pass
    return done


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", required=True)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--sample", default="all")
    p.add_argument("--mode", default="raw", choices=["raw", "hybrid_v4"])
    p.add_argument("--n-results", type=int, default=100)
    p.add_argument("--out", required=True)
    p.add_argument("--header", default="{}")
    args = p.parse_args()

    sys.path.insert(0, str(Path(args.repo) / "benchmarks"))
    import longmemeval_bench as bench  # the project's module, unchanged

    fresh = bench._fresh_collection
    bench._fresh_collection = lambda name="mempal_drawers": TimedCollection(fresh(name))
    retrieve = bench.build_palace_and_retrieve if args.mode == "raw" else bench.build_palace_and_retrieve_hybrid_v4

    data_dir = Path(args.data_dir)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    selected = None if args.sample == "all" else set(manifest["samples"][args.sample])
    out = Path(args.out)
    done = read_done(out, args.header)
    start = time.perf_counter()
    ran = 0
    with open(out, "a", encoding="utf-8") as log:
        for row in manifest["rows"]:
            qid = row["question_id"]
            if qid in done or (selected is not None and qid not in selected):
                continue
            entry = json.loads((data_dir / "q" / row["file"]).read_text(encoding="utf-8"))[0]
            TimedCollection.spent = 0.0
            t0 = time.perf_counter()
            rankings, _corpus, corpus_ids, _ts = retrieve(entry, granularity="session", n_results=args.n_results)
            total = time.perf_counter() - t0
            ranked = [bench.session_id_from_corpus_id(corpus_ids[i]) for i in rankings[: args.n_results]]
            log.write(json.dumps({
                "question_id": qid,
                "ranked_sessions": ranked,
                "items_returned": len(ranked),
                "documents": len(corpus_ids),
                "load_s": TimedCollection.spent,
                "query_ms": (total - TimedCollection.spent) * 1000,
                "rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20),
                "disk_mb": 0,
            }) + "\n")
            log.flush()
            ran += 1
            if ran % 10 == 0:
                print(f"{ran} questions, {time.perf_counter() - start:.0f} s", flush=True)
    print(f"done: {ran} questions run, {time.perf_counter() - start:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
