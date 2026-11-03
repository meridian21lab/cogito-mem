#!/usr/bin/env python3
"""Cogi's replies at each token budget on LongMemEval_M, from the frozen source, default settings, no reranker.

    PYTHONPATH=<data/frozen/src-b904848/src> .venv/bin/python budget_cogi.py --data-dir <split> --cache <copy of cache> --out rows.jsonl

A fresh memory per question, loaded and asked exactly as `eval long-history run` does in `search_arm` at cutoff `none`: top_k
300, the budget as max_tokens, no as_of. Each reply's items are kept with their message ids, so the scorer can
reproduce the published coverage by id and also apply the text rule used for every rival. Before the timed calls one
warm query embeds the question, so query times at each budget are for search and fill, and `first_query_ms` holds the embedding.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from cogito_mem.api import DEFAULT_TOP_K
from cogito_mem.evals.longmemeval import NO_BUDGET, load_question, make_embedder
from cogito_mem.memory import Config, Memory

BUDGETS = (1000, 2500, 5000)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--cache", required=True)
    p.add_argument("--sample", default="all")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    data = Path(args.data_dir)
    manifest = json.loads((data / "manifest.json").read_text())
    selected = None if args.sample == "all" else set(manifest["samples"][args.sample])
    embedder, rt = make_embedder("auto", None)
    cfg = Config(search="hybrid")
    settings = {"system": "cogi", "source": "data/frozen/src-b904848", "model": embedder.name, "dataset_sha256": manifest["dataset_sha256"],
                "search": "hybrid", "reranker": None, "as_of": "none", "top_k": DEFAULT_TOP_K, "budgets": BUDGETS}  # fmt: skip
    out = Path(args.out)
    done: set[str] = set()
    if out.exists() and out.stat().st_size:
        lines = out.read_text().split("\n")
        if json.loads(lines[0]).get("settings") != json.loads(json.dumps(settings)):
            raise SystemExit(f"{out} holds other settings: {lines[0][:300]}")
        for line in lines[1:]:
            try:
                done.add(json.loads(line)["question_id"])
            except (ValueError, KeyError):
                pass
    else:
        out.write_text(json.dumps({"settings": settings}) + "\n")
    start = time.perf_counter()
    ran = 0
    try:
        with open(out, "a") as log:
            for row in manifest["rows"]:
                qid = row["question_id"]
                if qid in done or (selected is not None and qid not in selected):
                    continue
                q = json.loads((data / "q" / row["file"]).read_text())[0]
                present = {str(s) for s in q["haystack_session_ids"]}
                want_sessions = {str(s) for s in q.get("answer_session_ids") or []} & present
                with Memory(None, embedder=embedder, config=cfg, cache_path=args.cache, embed_batch=32) as mem:
                    t0 = time.perf_counter()
                    evidence, _ = load_question(mem, q, evidence_sessions=want_sessions)
                    ns = mem.namespace("q")
                    mem.embed_pending(ns, limit=10**9)
                    mem.flush()
                    load_s = time.perf_counter() - t0
                    body = {"op": "query", "namespace": "q", "text": q["question"], "top_k": DEFAULT_TOP_K}
                    t1 = time.perf_counter()
                    mem.handle({**body, "max_tokens": NO_BUDGET})
                    first_ms = (time.perf_counter() - t1) * 1000
                    replies = {}
                    for n in BUDGETS:
                        t2 = time.perf_counter()
                        reply = mem.handle({**body, "max_tokens": n})
                        replies[str(n)] = {
                            "query_ms": (time.perf_counter() - t2) * 1000,
                            "tokens": reply["tokens"],
                            "items": [{"id": it["source"]["id"], "thread": it["thread_id"], "start": it["source"]["start"],
                                       "end": it["source"]["end"], "text": it["text"]} for it in reply["items"]],  # fmt: skip
                        }
                log.write(json.dumps({"question_id": qid, "evidence_ids": sorted(set(evidence)), "evidence_id_count": len(evidence),
                                      "load_s": load_s, "first_query_ms": first_ms, "replies": replies}) + "\n")  # fmt: skip
                log.flush()
                ran += 1
                if ran % 10 == 0:
                    print(f"{ran} questions, {time.perf_counter() - start:.0f} s", flush=True)
    finally:
        if rt is not None:
            rt.stop()
    print(f"done: {ran} questions run, {time.perf_counter() - start:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
