#!/usr/bin/env python3
"""MemPalace's product path on LongMemEval_M: `mine --mode convos`, then search, returning its drawers.

    python budget_mempalace.py --data-dir <split> --work <dir> --sample pilot20 --out rows.jsonl

Calls `convo_miner.mine_convos` and `searcher.search_memories`, what `mempalace mine` and `mempalace search` call. Sessions are
written as Claude Code JSONL, one file per session. Its benchmark's own path, session documents, is scored from the saved
rankings instead. MemPalace has no token budget: search returns `n_results` drawers (default 5, at most 800 characters each),
so this asks for 50 and the scorer fills each budget in that order, cutting at the limit.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import time
from pathlib import Path

N_RESULTS = 50


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--sample", default="all")
    p.add_argument("--out", required=True)
    p.add_argument("--header", default="{}")
    args = p.parse_args()
    from mempalace.convo_miner import mine_convos
    from mempalace.searcher import search_memories

    data_dir, work, out = Path(args.data_dir), Path(args.work), Path(args.out)
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
    start = time.perf_counter()
    ran = 0
    with open(out, "a", encoding="utf-8") as log:
        for row in manifest["rows"]:
            qid = row["question_id"]
            if qid in done or (selected is not None and qid not in selected):
                continue
            q = json.loads((data_dir / "q" / row["file"]).read_text(encoding="utf-8"))[0]
            root = work / "current"
            if root.exists():
                shutil.rmtree(root)
            convos = root / "convos"
            convos.mkdir(parents=True)
            for sid, turns in zip(q["haystack_session_ids"], q["haystack_sessions"]):
                with open(convos / f"{sid}.jsonl", "w", encoding="utf-8") as f:
                    for turn in turns:
                        content = turn["content"]
                        if turn["role"] == "assistant":
                            content = [{"type": "text", "text": turn["content"]}]
                        f.write(json.dumps({"type": turn["role"], "sessionId": sid, "message": {"role": turn["role"], "content": content}}) + "\n")
            palace = root / "palace"
            t0 = time.perf_counter()
            with contextlib.redirect_stdout(io.StringIO()):
                mine_convos(str(convos), str(palace), wing="q")
            load_s = time.perf_counter() - t0
            t1 = time.perf_counter()
            res = search_memories(q["question"], str(palace), n_results=N_RESULTS)
            ms = (time.perf_counter() - t1) * 1000
            if res.get("error"):
                raise RuntimeError(f"{qid}: {res}")
            hits = res.get("results") or []
            log.write(json.dumps({"question_id": qid, "ranked": [h.get("text") or h.get("content") or "" for h in hits], "query_ms": ms, "load_s": load_s}) + "\n")
            log.flush()
            ran += 1
            print(f"{ran} questions, {time.perf_counter() - start:.0f} s, load {load_s:.1f} s, hits {len(hits)}", flush=True)
    print(f"done: {ran} questions run, {time.perf_counter() - start:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
