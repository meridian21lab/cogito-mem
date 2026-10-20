"""The quality test: coverage at N tokens on LongMemEval (requirements §5).

    cogito-mem eval run --data longmemeval_m.json --arm U2 --out results/u2.json
    cogito-mem eval compare results/u1.json results/u2.json --budget 300

Each question gets a fresh namespace. Its history sessions are loaded with
``import: true`` in date order, one item per turn (``thread_id`` = session id,
``author`` = role, ``valid_at`` = session date + turn index in ms). The question
is asked with ``as_of`` = the question date, no filters, ``top_k`` = 100.

- Coverage at N: the share of questions where every evidence turn (``has_answer``)
  has at least one returned item within a ``max_tokens`` = N response.
- Recall@5 / @10 at turn level, ignoring the budget (``recall_all`` as in the
  LongMemEval paper's turn-level retrieval; ``recall_any`` too).
- The 30 abstention questions (``_abs``) are left out.
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
from ..embedding import HashEmbedder
from ..memory import Config, Memory
from .common import record, sha256_file, utc_now

ARMS = {
    "U1": {"search": "vector", "doc_context": "own"},
    "U2": {"search": "hybrid", "doc_context": "own"},
}
BUDGETS = (100, 300, 1000)
RECALL_KS = (5, 10)
NO_BUDGET = 100_000

_DATE = re.compile(r"(\d{4})/(\d{2})/(\d{2})(?:\s*\([A-Za-z]+\))?\s*(\d{2}):(\d{2})")


def parse_date(text: str) -> int:
    """LongMemEval dates look like '2023/05/20 (Sat) 02:21' and are taken as UTC."""
    m = _DATE.search(text)
    if not m:
        return timeutil.parse(text)
    y, mo, d, h, mi = (int(g) for g in m.groups())
    return timeutil.from_datetime(_dt.datetime(y, mo, d, h, mi, tzinfo=_dt.timezone.utc))


def load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"{path} should hold a list of LongMemEval questions")
    return data


def config_for(args: argparse.Namespace) -> Config:
    """The arms of requirements §7; ``--doc-author`` adds the author's name to any of them."""
    author = bool(getattr(args, "doc_author", False))
    if args.arm in ARMS:
        return Config(**ARMS[args.arm], doc_author=author)
    if args.arm == "U3":
        base = ARMS[args.base or "U2"]
        return Config(search=base["search"], doc_context="previous", doc_author=author)
    if args.arm == "R":
        base = ARMS.get(args.base or "U2") or ARMS["U2"]
        return Config(search=base["search"], doc_context=args.doc_context or base["doc_context"], doc_author=author)
    return Config(search=args.search or "hybrid", doc_context=args.doc_context or "own", doc_author=author)


def load_question(mem: Memory, q: dict, evidence_sessions: set[str] | None = None) -> tuple[list[str], int]:
    """Load the question's history. Returns (evidence message ids, evidence turns split into pieces).

    Evidence turns are the ``has_answer`` turns, only those of ``evidence_sessions`` when it is given.
    """
    sessions = list(zip(q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"]))
    order = sorted(range(len(sessions)), key=lambda i: (parse_date(sessions[i][1]), i))
    evidence: list[str] = []
    split_evidence = 0
    last = None
    for i in order:
        sid, date, turns = sessions[i]
        base = parse_date(date)
        if last is not None and base < last:
            base = last
        items, flags = [], []
        for t, turn in enumerate(turns):
            text = turn.get("content") or ""
            if not text.strip():
                continue
            items.append(
                {
                    "thread_id": str(sid),
                    "author": turn.get("role") or "user",
                    "valid_at": timeutil.format(base + t),
                    "text": text,
                }
            )
            flags.append(bool(turn.get("has_answer")) and (evidence_sessions is None or str(sid) in evidence_sessions))
        if not items:
            continue
        last = base + len(turns)
        resp = mem.handle({"op": "append", "namespace": "q", "import": True, "items": items})
        for flag, result in zip(flags, resp["items"]):
            if flag:
                evidence.append(result["id"])
                if result["pieces"] > 1:
                    split_evidence += 1
    return evidence, split_evidence


def evaluate(mem: Memory, q: dict, budgets=BUDGETS) -> dict:
    t0 = time.perf_counter()
    evidence, split_evidence = load_question(mem, q)
    ns = mem.namespace("q")
    mem.embed_pending(ns, limit=10**9)
    mem.flush()
    load_s = time.perf_counter() - t0
    as_of = timeutil.format(parse_date(q["question_date"]) + 59_999)
    base = {"op": "query", "namespace": "q", "text": q["question"], "as_of": as_of, "top_k": 100}
    want = set(evidence)
    covered = {}
    tokens = {}
    for n in budgets:
        resp = mem.handle({**base, "max_tokens": n})
        got = {item["source"]["id"] for item in resp["items"]}
        covered[str(n)] = bool(want) and want <= got
        tokens[str(n)] = resp["tokens"]
    resp = mem.handle({**base, "max_tokens": NO_BUDGET})
    turns: list[str] = []
    for item in resp["items"]:
        if item["source"]["id"] not in turns:
            turns.append(item["source"]["id"])
    out = {
        "question_id": q["question_id"],
        "question_type": q.get("question_type"),
        "evidence": len(evidence),
        "evidence_split": split_evidence,
        "covered": covered,
        "tokens": tokens,
        "load_s": round(load_s, 3),
    }
    for k in RECALL_KS:
        top = set(turns[:k])
        out[f"recall_all@{k}"] = bool(want) and want <= top
        out[f"recall_any@{k}"] = bool(want & top)
    return out


def summarize(rows: list[dict], budgets=BUDGETS) -> dict:
    scored = [r for r in rows if r["evidence"] > 0]
    n = len(scored) or 1
    summary: dict = {
        "questions": len(scored),
        "skipped_no_evidence": len(rows) - len(scored),
        "coverage": {str(b): round(sum(r["covered"][str(b)] for r in scored) / n, 4) for b in budgets},
        "evidence_turns": sum(r["evidence"] for r in scored),
        "evidence_split_share": round(
            sum(r["evidence_split"] for r in scored) / max(sum(r["evidence"] for r in scored), 1), 4
        ),
    }
    for k in RECALL_KS:
        for kind in ("all", "any"):
            key = f"recall_{kind}@{k}"
            summary[key] = round(sum(r[key] for r in scored) / n, 4)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        by_type[r.get("question_type") or "unknown"].append(r)
    gate = str(300 if 300 in budgets else budgets[0])
    summary[f"coverage_{gate}_by_type"] = {
        t: {"n": len(rs), "coverage": round(sum(r["covered"][gate] for r in rs) / len(rs), 4)}
        for t, rs in sorted(by_type.items())
    }
    return summary


def make_embedder(kind: str, root: Path | None):
    if kind == "hash":
        return HashEmbedder(), None
    from ..runtime import LlamaRuntime

    rt = LlamaRuntime.from_environment(root)
    rt.start()
    return rt.embedder(), rt


def cmd_run(args: argparse.Namespace) -> int:
    data_path = Path(args.data)
    questions = [q for q in load(data_path) if not str(q["question_id"]).endswith("_abs")]
    if args.limit:
        questions = questions[: args.limit]
    cfg = config_for(args)
    embedder, rt = make_embedder(args.embedder, Path(args.root).expanduser() if args.root else None)
    reranker = rr_server = None
    if args.arm == "R" or args.reranker:
        if not args.reranker:
            print("arm R needs --reranker (a reranker GGUF or llama-server URL)", file=sys.stderr)
            return 2
        from ..runtime import start_reranker

        reranker, rr_server = start_reranker(args.reranker, None)
    budgets = tuple(int(b) for b in args.budgets.split(","))
    meta = record(embedder.name)
    meta.update(
        {
            "dataset": str(data_path),
            "dataset_sha256": sha256_file(data_path),
            "arm": args.arm,
            "config": {"search": cfg.search, "doc_context": cfg.doc_context, "doc_author": cfg.doc_author,
                       "candidates": cfg.candidates},
            "reranker": getattr(reranker, "name", None),
        }
    )
    rows: list[dict] = []
    t0 = time.perf_counter()
    try:
        for i, q in enumerate(questions):
            with Memory(
                None, embedder=embedder, config=cfg, cache_path=args.cache, reranker=reranker, embed_batch=args.batch
            ) as mem:
                rows.append(evaluate(mem, q, budgets))
            if args.verbose or (i + 1) % 10 == 0 or i + 1 == len(questions):
                s = summarize(rows, budgets)
                print(
                    f"[{i + 1}/{len(questions)}] coverage@{budgets} = "
                    + ", ".join(f"{s['coverage'][str(b)]:.3f}" for b in budgets)
                    + f"  R@5 {s['recall_all@5']:.3f}  R@10 {s['recall_all@10']:.3f}"
                    + f"  ({time.perf_counter() - t0:.0f} s)",
                    file=sys.stderr,
                )
    finally:
        if rt is not None:
            rt.stop()
        if rr_server is not None:
            rr_server.stop()
    meta["finished_utc"] = utc_now()
    summary = summarize(rows, budgets)
    if args.build_check:
        r5, r10 = (float(x) for x in args.build_check.split(","))
        summary["build_check"] = {
            "paper_recall@5": r5,
            "paper_recall@10": r10,
            "ok": summary["recall_all@5"] >= r5 - 0.05 and summary["recall_all@10"] >= r10 - 0.05,
        }
    result = {"meta": meta, "summary": summary, "per_question": rows}
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    print(json.dumps(summary, indent=2))
    return 0


def paired_bootstrap(a: list[float], b: list[float], n_boot: int = 10_000, seed: int = 0) -> tuple[float, float, float]:
    """Mean of b - a with a 95 % percentile bootstrap interval over questions."""
    rng = random.Random(seed)
    diffs = [y - x for x, y in zip(a, b)]
    n = len(diffs)
    mean = sum(diffs) / n
    means = []
    for _ in range(n_boot):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return mean, means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def cmd_compare(args: argparse.Namespace) -> int:
    a = json.loads(Path(args.a).read_text())
    b = json.loads(Path(args.b).read_text())
    key = str(args.budget)
    ra = {r["question_id"]: r for r in a["per_question"] if r["evidence"] > 0}
    rb = {r["question_id"]: r for r in b["per_question"] if r["evidence"] > 0}
    common = sorted(set(ra) & set(rb))
    if not common:
        print("no questions in common", file=sys.stderr)
        return 1
    if a["meta"].get("dataset_sha256") != b["meta"].get("dataset_sha256"):
        print("warning: the two results used different dataset files", file=sys.stderr)
    xa = [float(ra[q]["covered"][key]) for q in common]
    xb = [float(rb[q]["covered"][key]) for q in common]
    mean, lo, hi = paired_bootstrap(xa, xb, args.bootstrap, args.seed)
    out = {
        "budget": args.budget,
        "questions": len(common),
        "a": {"file": args.a, "arm": a["meta"].get("arm"), "coverage": round(sum(xa) / len(xa), 4)},
        "b": {"file": args.b, "arm": b["meta"].get("arm"), "coverage": round(sum(xb) / len(xb), 4)},
        "difference_points": round(100 * mean, 2),
        "ci95_points": [round(100 * lo, 2), round(100 * hi, 2)],
        "counts": abs(mean) >= 0.05,
        "rule": "a difference counts only if it is 5 points or more (requirements §5)",
    }
    print(json.dumps(out, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cogito-mem eval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run one arm on LongMemEval")
    r.add_argument("--data", required=True, help="longmemeval_m.json (or _s / _oracle for pipeline checks)")
    r.add_argument("--arm", default="U2", choices=["U1", "U2", "U3", "R", "custom"])
    r.add_argument("--base", choices=["U1", "U2"], help="for U3 and R: the arm they build on (default U2)")
    r.add_argument("--search", choices=["hybrid", "vector", "keyword"], help="for --arm custom")
    r.add_argument("--doc-context", choices=["own", "previous"], help="for --arm custom or R")
    r.add_argument("--doc-author", action="store_true", help="put each author's name before their text")
    r.add_argument("--reranker", help="reranker GGUF path or llama-server URL (arm R)")
    r.add_argument("--embedder", default="auto", choices=["auto", "hash"], help="hash: pipeline checks only")
    r.add_argument("--cache", default=str(Path.home() / ".cogito-mem" / "cache" / "embeddings.sqlite3"))
    r.add_argument("--root", help="where llama.cpp and the model live (default ~/.cogito-mem)")
    r.add_argument("--budgets", default=",".join(str(b) for b in BUDGETS))
    r.add_argument("--batch", type=int, default=32, help="inputs per embedding request")
    r.add_argument("--limit", type=int, help="first N questions only (pipeline checks)")
    r.add_argument("--build-check", help="the paper's turn-level R@5,R@10 for a comparable model, e.g. 0.60,0.72")
    r.add_argument("--out", help="write the full result (with per-question rows) here")
    r.add_argument("--verbose", action="store_true")
    r.set_defaults(func=cmd_run)
    c = sub.add_parser("compare", help="paired difference of two runs with a 95 %% bootstrap interval")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--budget", type=int, default=300)
    c.add_argument("--bootstrap", type=int, default=10_000)
    c.add_argument("--seed", type=int, default=0)
    c.set_defaults(func=cmd_compare)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)
