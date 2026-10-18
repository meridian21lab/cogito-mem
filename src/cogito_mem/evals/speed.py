"""The speed test (requirements §6).

    cogito-mem bench speed --data longmemeval_m.json --tokens 10M --queries 1000 --out results/speed.json

- Query time is measured inside the warm process, from the parsed request to the
  serialised response, one query at a time; the localhost HTTP round trip is
  measured separately. Reported: median, p95 (the gate: <= 100 ms) and maximum.
- The memory is filled with LongMemEval sessions, deduplicated and concatenated up
  to the size; the session ids used are recorded. ``--synthetic`` makes text instead
  (for pipeline checks only).
- Append: time of the call for 512 / 1k / 2k / 4k / 8k-token messages, and the time
  until a new item can be found by meaning (its vector is stored).

Embedding 10M tokens on a laptop CPU takes hours. Fill the embedding cache on a GPU
machine (``--embed-only``), copy ``embeddings.sqlite3`` over, and the laptop run reads
the vectors from it; or pass ``--random-vectors`` to time search alone.
Set ``COGITO_MEM_GPU_LAYERS=0`` for the CPU-only gate.
"""

from __future__ import annotations

import argparse
import http.client
import itertools
import json
import random
import statistics
import sys
import threading
import time
from pathlib import Path

import numpy as np

from .. import timeutil
from ..embedding import DIM
from ..memory import Config, Memory
from ..tokenizer import count
from .common import parse_count, record, utc_now
from .longmemeval import load, make_embedder, parse_date


def _stats(ms: list[float]) -> dict:
    if not ms:
        return {}
    xs = sorted(ms)
    p95 = xs[min(len(xs) - 1, int(round(0.95 * len(xs))) - 1)]
    return {
        "n": len(xs),
        "median_ms": round(statistics.median(xs), 3),
        "p95_ms": round(p95, 3),
        "max_ms": round(xs[-1], 3),
        "mean_ms": round(statistics.fmean(xs), 3),
    }


class Synthetic:
    """Deterministic chat-like text from a Zipf vocabulary (pipeline checks only)."""

    def __init__(self, seed: int = 0, vocab: int = 20000):
        self.rng = random.Random(seed)
        syll = ["ka", "lo", "mi", "ra", "te", "su", "no", "vi", "de", "ba", "po", "ze", "qu", "fi", "ga", "hu"]
        words = set()
        while len(words) < vocab:
            words.add("".join(self.rng.choice(syll) for _ in range(self.rng.randint(1, 4))))
        self.words = sorted(words)
        self.cum_weights = list(itertools.accumulate(1.0 / (i + 1) for i in range(vocab)))

    def sentence(self, n: int | None = None) -> str:
        n = n or self.rng.randint(6, 18)
        ws = self.rng.choices(self.words, cum_weights=self.cum_weights, k=n)
        return " ".join(ws).capitalize() + "."

    def message(self, sentences: int) -> str:
        return " ".join(self.sentence() for _ in range(sentences))

    def sessions(self):
        i = 0
        while True:
            turns = [
                {"role": "user" if t % 2 == 0 else "assistant", "content": self.message(self.rng.randint(1, 8))}
                for t in range(self.rng.randint(4, 14))
            ]
            yield f"syn-{i}", f"2024/01/01 (Mon) 00:00", turns
            i += 1


def _lme_sessions(questions: list[dict]):
    seen = set()
    for q in questions:
        for sid, date, turns in zip(q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"]):
            if sid in seen:
                continue
            seen.add(sid)
            yield sid, date, turns


def fill(mem: Memory, sessions, target_tokens: int) -> tuple[list[str], int]:
    ns = mem.namespace("bench")
    used: list[str] = []
    total = 0
    clock = timeutil.parse("2020-01-01T00:00:00Z")
    for sid, date, turns in sessions:
        try:
            base = max(parse_date(date), clock)
        except ValueError:
            base = clock
        items = [
            {"thread_id": str(sid), "author": t.get("role") or "user", "valid_at": timeutil.format(base + i),
             "text": t["content"]}
            for i, t in enumerate(turns) if (t.get("content") or "").strip()
        ]  # fmt: skip
        if not items:
            continue
        clock = base + len(turns)
        mem.handle({"op": "append", "namespace": "bench", "import": True, "items": items})
        used.append(str(sid))
        total = int(ns._row_tokens.view().sum())
        if total >= target_tokens:
            break
    return used, total


def random_vectors(mem: Memory, seed: int = 0) -> None:
    ns = mem.namespace("bench")
    rng = np.random.default_rng(seed)
    while True:
        rows = ns.take_pending(100_000)
        if not rows:
            return
        v = rng.standard_normal((len(rows), DIM)).astype(np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        ns.set_vectors(rows, v.astype(np.float16).astype(np.float32))


def time_queries(mem: Memory, texts: list[str], warmup: int = 20) -> list[float]:
    for t in texts[:warmup]:
        json.dumps(mem.handle({"op": "query", "namespace": "bench", "text": t + " warm-up"}))
    out = []
    for t in texts:
        t0 = time.perf_counter()
        resp = mem.handle({"op": "query", "namespace": "bench", "text": t, "top_k": 10, "max_tokens": 300})
        json.dumps(resp, ensure_ascii=False)
        out.append((time.perf_counter() - t0) * 1000)
    return out


def time_http(mem: Memory, texts: list[str]) -> list[float]:
    from ..server import MemoryServer

    server = MemoryServer(mem, port=0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=60)
        out = []
        for t in texts:
            body = json.dumps({"op": "query", "namespace": "bench", "text": t, "top_k": 10, "max_tokens": 300})
            t0 = time.perf_counter()
            conn.request("POST", "/v1/memory", body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            resp.read()
            out.append((time.perf_counter() - t0) * 1000)
        conn.close()
        return out
    finally:
        server.shutdown()
        server.server_close()


def make_text(mem: Memory, source: list[str], tokens: int) -> str:
    parts, n = [], 0
    while n < tokens:
        part = random.choice(source)
        parts.append(part)
        n += count(mem.tokenizer, part)
    text = "\n\n".join(parts)
    ends = mem.tokenizer.offsets(text)
    return text[: ends[tokens - 1]] if len(ends) > tokens else text


def time_appends(mem: Memory, source: list[str], sizes: list[int], reps: int) -> dict:
    out = {}
    for size in sizes:
        ms = []
        for r in range(reps):
            text = make_text(mem, source, size) + f" (append test {size}-{r}-{time.time_ns()})"
            t0 = time.perf_counter()
            mem.handle({"op": "append", "namespace": "bench-append", "items": [{"author": "bench", "text": text}]})
            ms.append((time.perf_counter() - t0) * 1000)
        out[str(size)] = _stats(ms)
    return out


def time_to_meaning(mem: Memory, source: list[str], reps: int, timeout: float = 120.0) -> dict:
    if mem.embedder is None:
        return {}
    ns = mem.namespace("bench-append")
    mem.flush(timeout)
    ms = []
    for r in range(reps):
        text = random.choice(source) + f" (meaning test {r}-{time.time_ns()})"
        t0 = time.perf_counter()
        resp = mem.handle({"op": "append", "namespace": "bench-append", "items": [{"author": "bench", "text": text}]})
        item_id = resp["items"][0]["id"]
        while not ns.has_vector(item_id):
            if time.perf_counter() - t0 > timeout:
                break
            time.sleep(0.001)
        ms.append((time.perf_counter() - t0) * 1000)
    return _stats(ms)


def cmd_speed(args: argparse.Namespace) -> int:
    random.seed(args.seed)
    target = parse_count(args.tokens)
    embedder, rt = make_embedder(args.embedder, Path(args.root).expanduser() if args.root else None)
    meta = record(embedder.name)
    try:
        if args.data:
            questions = load(Path(args.data))
            sessions = _lme_sessions(questions)
            query_texts = [q["question"] for q in questions]
        else:
            syn = Synthetic(args.seed)
            sessions = syn.sessions()
            query_texts = [syn.sentence(random.randint(6, 14)) + "?" for _ in range(2000)]
        mem = Memory(None, embedder=embedder, config=Config(search=args.search), cache_path=args.cache,
                     query_cache=0, embed_batch=args.batch)  # fmt: skip
        t0 = time.perf_counter()
        used, total = fill(mem, sessions, target)
        fill_s = time.perf_counter() - t0
        ns = mem.namespace("bench")
        print(f"filled {total} tokens, {len(ns.row_ids)} items in {fill_s:.1f} s", file=sys.stderr)
        t0 = time.perf_counter()
        if args.random_vectors:
            random_vectors(mem, args.seed)
        else:
            while mem.embed_pending(ns, limit=4096):
                done = int(ns._has_vec.view().sum())
                print(f"\rembedded {done}/{len(ns.row_ids)}", end="", file=sys.stderr)
            print(file=sys.stderr)
        embed_s = time.perf_counter() - t0
        if args.embed_only:
            print(json.dumps({"tokens": total, "items": len(ns.row_ids), "embed_s": round(embed_s, 1)}))
            return 0
        texts = [query_texts[i % len(query_texts)] for i in range(args.queries)]
        if len(set(texts)) < len(texts):  # repeated questions: make each text unique so nothing is cached
            texts = [f"{t} ({i})" if i >= len(query_texts) else t for i, t in enumerate(texts)]
        results = {
            "memory": {
                "tokens": total,
                "items": len(ns.row_ids),
                "messages": len(ns.messages),
                "sessions": len(used),
                "fill_s": round(fill_s, 1),
                "embed_s": round(embed_s, 1),
                "random_vectors": args.random_vectors,
                "search": args.search,
            },
            "query_in_process": _stats(time_queries(mem, texts)),
        }
        if args.http:
            results["query_http_round_trip"] = _stats(time_http(mem, texts[: args.http]))
        source = [m.text for m in ns.messages[:5000] if len(m.text) > 50] or ["filler text"]
        if args.append_sizes:
            sizes = [parse_count(s) for s in args.append_sizes.split(",")]
            results["append_call"] = time_appends(mem, source, sizes, args.append_reps)
            results["time_to_searchable_by_meaning"] = time_to_meaning(mem, source, args.append_reps)
        results["gate_p95_ms"] = 100
        results["gate_passed"] = results["query_in_process"]["p95_ms"] <= 100
        meta["finished_utc"] = utc_now()
        meta["data"] = args.data or "synthetic"
        meta["sessions_used"] = used if args.data else len(used)
        out = {"meta": meta, "results": results}
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(out, indent=2))
        print(json.dumps(results, indent=2))
        mem.close()
        return 0
    finally:
        if rt is not None:
            rt.stop()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cogito-mem bench", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("speed", help="query and append timing")
    s.add_argument("--data", help="a LongMemEval file to fill the memory from (default: synthetic text)")
    s.add_argument("--tokens", default="10M", help="memory size, e.g. 10M or 100M")
    s.add_argument("--queries", type=int, default=1000)
    s.add_argument("--http", type=int, default=200, help="queries to time over HTTP (0: skip)")
    s.add_argument("--search", default="hybrid", choices=["hybrid", "vector", "keyword"])
    s.add_argument("--embedder", default="auto", choices=["auto", "hash"])
    s.add_argument("--cache", default=str(Path.home() / ".cogito-mem" / "cache" / "embeddings.sqlite3"))
    s.add_argument("--root", help="where llama.cpp and the model live (default ~/.cogito-mem)")
    s.add_argument("--random-vectors", action="store_true", help="do not embed the memory; time search only")
    s.add_argument("--embed-only", action="store_true", help="fill the embedding cache and stop")
    s.add_argument("--batch", type=int, default=32)
    s.add_argument("--append-sizes", default="512,1k,2k,4k,8k")
    s.add_argument("--append-reps", type=int, default=10)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out")
    s.set_defaults(func=cmd_speed)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)
