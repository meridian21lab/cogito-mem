"""Retrieval quality on LoCoMo, against what an agent gets without a memory.

    cogito-mem eval locomo --data locomo10.json --search hybrid --out results/locomo-hybrid.json

LoCoMo (Maharana et al., ACL 2024; github.com/snap-research/locomo) holds 10 long
conversations between two people over up to 35 sessions, with about 2,000 questions
whose answers are labelled with the turns that hold them (``evidence``). That makes
it scorable with no judging model, like LongMemEval in requirements §5.

Each conversation is loaded into a fresh namespace with ``import: true`` (one item per
turn, ``thread_id`` = session, ``author`` = speaker, ``valid_at`` = session time + turn
index in ms; an image a speaker shares is added as ``[shares a photo of …]``). Each
question is asked with ``as_of`` after the last session and no filters.

- **coverage@N**: the share of questions whose evidence turns are all returned within
  ``max_tokens`` = N (the pass-mark metric of §5).
- **recall_all@k / recall_any@k**: turn-level, ignoring the budget.

The same budget is given to two memory-less baselines: **recent** (the last N tokens
of the conversation, i.e. a context window) and **random** (random turns up to N
tokens). The 446 adversarial questions (category 5, no answer in the conversation)
are left out, as LongMemEval's abstention questions are.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from .. import timeutil
from ..memory import Config, Memory
from .common import record, sha256_file, utc_now
from .longmemeval import NO_BUDGET, make_embedder, paired_bootstrap

CATEGORIES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop", 5: "adversarial"}
BUDGETS = (100, 300, 1000)
RECALL_KS = (1, 5, 10)
_EVIDENCE = re.compile(r"D:?(\d+):(\d+)")


def parse_when(text: str) -> int:
    """LoCoMo session times look like '1:56 pm on 8 May, 2023' (taken as UTC)."""
    dt = _dt.datetime.strptime(" ".join(text.split()), "%I:%M %p on %d %B, %Y")
    return timeutil.from_datetime(dt.replace(tzinfo=_dt.timezone.utc))


def evidence_ids(raw: list[str]) -> list[str]:
    out = []
    for entry in raw or []:
        for s, t in _EVIDENCE.findall(entry):
            dia = f"D{int(s)}:{int(t)}"
            if dia not in out:
                out.append(dia)
    return out


def sessions(conv: dict) -> list[tuple[int, int, list[dict]]]:
    out = []
    for key, value in conv.items():
        m = re.fullmatch(r"session_(\d+)", key)
        if m and isinstance(value, list) and value:
            out.append((int(m.group(1)), parse_when(conv[f"{key}_date_time"]), value))
    return sorted(out, key=lambda s: (s[1], s[0]))


def turn_text(turn: dict) -> str:
    text = turn.get("text") or ""
    caption = turn.get("blip_caption")
    if caption:
        text = f"{text} [shares {caption}]".strip()
    return text


def load_conversation(mem: Memory, sample: dict) -> tuple[dict[str, str], dict[str, int], list[str], int]:
    """Returns (dia_id -> message id, message id -> tokens, message ids in time order, last valid_at)."""
    ids: dict[str, str] = {}
    order: list[str] = []
    last = 0
    for number, when, turns in sessions(sample["conversation"]):
        items, dias = [], []
        base = max(when, last)
        for i, turn in enumerate(turns):
            text = turn_text(turn)
            if not text:
                continue
            items.append({"thread_id": f"session_{number}", "author": turn.get("speaker") or "unknown",
                          "valid_at": timeutil.format(base + i), "text": text})  # fmt: skip
            dias.append(turn.get("dia_id"))
        last = base + len(turns)
        resp = mem.handle({"op": "append", "namespace": "c", "import": True, "items": items})
        for dia, result in zip(dias, resp["items"]):
            ids[dia] = result["id"]
            order.append(result["id"])
    ns = mem.namespace("c")
    tokens = {}
    for msg in ns.messages:
        tokens[msg.id] = int(sum(ns._row_tokens.data[r] for r in msg.rows))
    return ids, tokens, order, last


def baseline_sets(order: list[str], tokens: dict[str, int], budget: int, rng: random.Random) -> tuple[set, set]:
    recent: set[str] = set()
    used = 0
    for mid in reversed(order):
        if used + tokens[mid] > budget:
            break
        recent.add(mid)
        used += tokens[mid]
    shuffled = order[:]
    rng.shuffle(shuffled)
    rand: set[str] = set()
    used = 0
    for mid in shuffled:
        if used + tokens[mid] <= budget:
            rand.add(mid)
            used += tokens[mid]
    return recent, rand


def evaluate_sample(mem: Memory, sample: dict, budgets, rng: random.Random) -> list[dict]:
    ids, tokens, order, last = load_conversation(mem, sample)
    ns = mem.namespace("c")
    mem.embed_pending(ns, limit=10**9)
    mem.flush()
    as_of = timeutil.format(last + 60_000)
    total_tokens = sum(tokens.values())
    rows = []
    for qi, qa in enumerate(sample["qa"]):
        category = qa.get("category")
        if category == 5:
            continue
        want = {ids[d] for d in evidence_ids(qa.get("evidence")) if d in ids}
        row = {"sample_id": sample.get("sample_id"), "q": qi, "category": CATEGORIES.get(category, str(category)),
               "evidence": len(want), "conversation_tokens": total_tokens}  # fmt: skip
        if not want:
            rows.append(row)
            continue
        base = {"op": "query", "namespace": "c", "text": qa["question"], "as_of": as_of, "top_k": 100}
        t0 = time.perf_counter()
        resp = mem.handle({**base, "max_tokens": NO_BUDGET})
        row["query_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        ranked: list[str] = []
        for item in resp["items"]:
            if item["source"]["id"] not in ranked:
                ranked.append(item["source"]["id"])
        for k in RECALL_KS:
            top = set(ranked[:k])
            row[f"recall_all@{k}"] = want <= top
            row[f"recall_any@{k}"] = bool(want & top)
        row["covered"], row["recent"], row["random"] = {}, {}, {}
        for n in budgets:
            got = {i["source"]["id"] for i in mem.handle({**base, "max_tokens": n})["items"]}
            recent, rand = baseline_sets(order, tokens, n, rng)
            row["covered"][str(n)] = want <= got
            row["recent"][str(n)] = want <= recent
            row["random"][str(n)] = want <= rand
        rows.append(row)
    return rows


def summarize(rows: list[dict], budgets) -> dict:
    scored = [r for r in rows if r["evidence"] > 0]
    n = len(scored) or 1

    def share(key: str, b: str | None = None, rs=None) -> float:
        rs = scored if rs is None else rs
        if not rs:
            return 0.0
        return round(sum(bool(r[key][b] if b else r[key]) for r in rs) / len(rs), 4)

    summary = {
        "questions": len(scored),
        "skipped_no_evidence": len(rows) - len(scored),
        "mean_conversation_tokens": round(sum(r["conversation_tokens"] for r in scored) / n),
        "coverage": {str(b): share("covered", str(b)) for b in budgets},
        "baseline_recent": {str(b): share("recent", str(b)) for b in budgets},
        "baseline_random": {str(b): share("random", str(b)) for b in budgets},
    }
    for k in RECALL_KS:
        summary[f"recall_all@{k}"] = share(f"recall_all@{k}")
        summary[f"recall_any@{k}"] = share(f"recall_any@{k}")
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        by_cat[r["category"]].append(r)
    gate = str(300 if 300 in budgets else budgets[0])
    summary[f"by_category@{gate}"] = {
        c: {"n": len(rs), "coverage": share("covered", gate, rs), "recent": share("recent", gate, rs),
            "recall_all@10": share("recall_all@10", None, rs)}  # fmt: skip
        for c, rs in sorted(by_cat.items())
    }
    times = sorted(r["query_ms"] for r in scored if "query_ms" in r)
    if times:
        summary["query_ms"] = {"median": times[len(times) // 2], "p95": times[int(0.95 * (len(times) - 1))]}
    return summary


def cmd_run(args: argparse.Namespace) -> int:
    data_path = Path(args.data)
    samples = json.loads(data_path.read_text())
    if args.limit:
        samples = samples[: args.limit]
    cfg = Config(search=args.search, doc_context=args.doc_context, doc_author=args.doc_author)
    embedder, rt = (None, None) if args.search == "keyword" else make_embedder(
        args.embedder, Path(args.root).expanduser() if args.root else None
    )
    reranker = rr_server = None
    if args.reranker:
        from ..runtime import start_reranker

        reranker, rr_server = start_reranker(args.reranker, None)
    budgets = tuple(int(b) for b in args.budgets.split(","))
    meta = record(embedder.name if embedder is not None else None)
    meta.update({"dataset": str(data_path), "dataset_sha256": sha256_file(data_path),
                 "config": {"search": cfg.search, "doc_context": cfg.doc_context, "doc_author": cfg.doc_author},
                 "reranker": getattr(reranker, "name", None)})  # fmt: skip
    rng = random.Random(args.seed)
    rows: list[dict] = []
    t0 = time.perf_counter()
    try:
        for i, sample in enumerate(samples):
            with Memory(None, embedder=embedder, config=cfg, cache_path=args.cache, reranker=reranker,
                        embed_batch=args.batch) as mem:  # fmt: skip
                rows.extend(evaluate_sample(mem, sample, budgets, rng))
            s = summarize(rows, budgets)
            print(f"[{i + 1}/{len(samples)}] coverage@300 {s['coverage'].get('300')}  recent {s['baseline_recent'].get('300')}"
                  f"  R@10 {s['recall_all@10']}  ({time.perf_counter() - t0:.0f} s)", file=sys.stderr)  # fmt: skip
    finally:
        if rt is not None:
            rt.stop()
        if rr_server is not None:
            rr_server.stop()
    meta["finished_utc"] = utc_now()
    summary = summarize(rows, budgets)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"meta": meta, "summary": summary, "per_question": rows}, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    a = json.loads(Path(args.a).read_text())
    b = json.loads(Path(args.b).read_text())
    key = str(args.budget)

    def index(res):
        return {(r["sample_id"], r["q"]): r for r in res["per_question"] if r["evidence"] > 0}

    ra, rb = index(a), index(b)
    common = sorted(set(ra) & set(rb))
    xa = [float(ra[q]["covered"][key]) for q in common]
    xb = [float(rb[q]["covered"][key]) for q in common]
    mean, lo, hi = paired_bootstrap(xa, xb, args.bootstrap, args.seed)
    print(json.dumps({"budget": args.budget, "questions": len(common), "a": round(sum(xa) / len(xa), 4),
                      "b": round(sum(xb) / len(xb), 4), "difference_points": round(100 * mean, 2),
                      "ci95_points": [round(100 * lo, 2), round(100 * hi, 2)]}, indent=2))  # fmt: skip
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cogito-mem eval locomo", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("compare", help="paired difference of two runs")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--budget", type=int, default=300)
    c.add_argument("--bootstrap", type=int, default=10_000)
    c.add_argument("--seed", type=int, default=0)
    c.set_defaults(func=cmd_compare)
    p.add_argument("--data", help="locomo10.json")
    p.add_argument("--search", default="hybrid", choices=["hybrid", "vector", "keyword"])
    p.add_argument("--doc-context", default="own", choices=["own", "previous"])
    p.add_argument("--doc-author", action="store_true", help="put the speaker's name before each turn's text")
    p.add_argument("--reranker", help="reranker GGUF path or llama-server URL")
    p.add_argument("--embedder", default="auto", choices=["auto", "hash"])
    p.add_argument("--cache", default=str(Path.home() / ".cogito-mem" / "cache" / "embeddings.sqlite3"))
    p.add_argument("--root", help="where llama.cpp and the model live (default ~/.cogito-mem)")
    p.add_argument("--budgets", default=",".join(str(b) for b in BUDGETS))
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--limit", type=int, help="first N conversations only")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out")
    p.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.func is cmd_run and not args.data:
        build_parser().error("--data is required")
    return int(args.func(args) or 0)
