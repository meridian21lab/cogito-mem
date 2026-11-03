#!/usr/bin/env python3
"""How much disk one question's documents take in a persistent Chroma store.

The benchmark runs in memory, so its run files can't say. This builds the raw mode's documents for one question
(first in the file with a median-size haystack) in chromadb.PersistentClient, the backend the product uses, and adds up the
folder. A single measurement, of the store only.

    python mempalace_disk.py <split folder> <empty folder>
"""
from __future__ import annotations

import json
import resource
import statistics
import sys
import time
from pathlib import Path

import chromadb


def main() -> int:
    data, folder = Path(sys.argv[1]), Path(sys.argv[2])
    manifest = json.loads((data / "manifest.json").read_text())
    median = statistics.median_low(len(r["haystack_session_ids"]) for r in manifest["rows"])
    row = next(r for r in manifest["rows"] if len(r["haystack_session_ids"]) == median)
    entry = json.loads((data / "q" / row["file"]).read_text())[0]
    docs = ["\n".join(t["content"] for t in s if t["role"] == "user") for s in entry["haystack_sessions"]]
    docs = [d for d in docs if d]
    client = chromadb.PersistentClient(path=str(folder))
    collection = client.create_collection("probe")
    t0 = time.perf_counter()
    collection.add(documents=docs, ids=[f"doc_{i}" for i in range(len(docs))])
    took = time.perf_counter() - t0
    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
    print(json.dumps({"question_id": row["question_id"], "documents": len(docs), "disk_mb": round(size / (1 << 20), 1),
                      "add_s": round(took, 2), "rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20))}))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
