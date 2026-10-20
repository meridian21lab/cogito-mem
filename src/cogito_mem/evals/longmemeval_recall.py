"""Retrieval recall on LongMemEval-S, the number other local memory tools publish.

    cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --out results/lme-recall/hybrid.json
    cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --search keyword --out results/lme-recall/keyword.json
    cogito-mem eval longmemeval-recall compare results/lme-recall/keyword.json results/lme-recall/hybrid.json

LongMemEval (Wu et al., ICLR 2025; github.com/xiaowu0162/LongMemEval) gives each of its
500 questions a history of about 50 chat sessions (about 115k tokens in the _s file) and
labels the sessions that hold the answer (``answer_session_ids``) and, inside them, the
turns (``has_answer``). That makes retrieval scorable with no judging model.

Each question gets a fresh memory, loaded as ``eval run`` loads it
(``longmemeval.load_question``: one item per turn of either role, ``thread_id`` = session
id, ``author`` = role, ``valid_at`` = session date + turn index in ms, ``import: true``).
The question is asked through the normal query path with ``as_of`` = the question date,
``top_k`` = 100 and no token budget. The returned items, in order, rank the turns; the
sessions of those turns, in the order they first appear, rank the sessions.

- **Session level**, against ``answer_session_ids``. ``recall_any@k`` (R@k): an evidence
  session is among the first k sessions. This is the "R@5" that deja-vu, MemPalace, iai and
  agentmemory publish (deja-vu calls it hit@k). ``recall_all@k``: every evidence session
  is; LongMemEval's own retrieval script prints this one. k = 1, 3, 5, 10.
- **Turn level**, against the ``has_answer`` turns of the evidence sessions: the same two
  over distinct turns. Questions with no such turn are left out of it.
- **NDCG@10** (binary relevance; the ideal ranking puts every evidence session, or turn,
  first) and **MRR** (1 / rank of the first evidence session; 0 if no returned item is in one).

The 30 abstention questions (``_abs`` in the id) are reported three ways: **all** scores
them like the others against their ``answer_session_ids`` (deja-vu's 97.2 and MemPalace's
96.6 are over all 500); **answerable** leaves them out, as LongMemEval's retrieval
evaluation does (470 questions); **abstention** shows them alone. Unlike LongMemEval's
script, which indexes user turns only (and so also drops the questions whose evidence is in
an assistant turn), the memory holds both roles, as it does in use.

``--questions-out`` writes each question's outcome as it finishes (JSON lines); a rerun
with the same file skips the questions already in it, and the embedding cache makes
re-embedding free, so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

from .. import timeutil
from ..api import MAX_TOP_K
from ..memory import Config, Memory
from .common import record, sha256_file, utc_now
from .longmemeval import NO_BUDGET, load, load_question, make_embedder, paired_bootstrap, parse_date

KS = (1, 3, 5, 10)
NDCG_K = 10
KEEP_RANKED = 20  # session ids kept per question, best first
TYPES = ("single-session-user", "single-session-assistant", "single-session-preference", "multi-session",
         "temporal-reasoning", "knowledge-update")  # fmt: skip
SETS = ("all", "answerable", "abstention")
COMPARE_METRICS = "session_recall_any@5,session_recall_any@10,session_recall_all@5,session_ndcg@10"


def is_abstention(question_id: str) -> bool:
    return "_abs" in str(question_id)


def distinct(ids) -> list[str]:
    """The ids in order of first appearance."""
    return list(dict.fromkeys(ids))


def ndcg(ranked: list[str], relevant: set[str], k: int = NDCG_K) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, x in enumerate(ranked[:k]) if x in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


def score(ranked: list[str], relevant: set[str], ks=KS) -> dict:
    """One ranking (distinct ids, best first) against a non-empty set of relevant ids."""
    rank = next((i + 1 for i, x in enumerate(ranked) if x in relevant), None)
    out: dict = {"rank": rank}
    for k in ks:
        top = set(ranked[:k])
        out[f"recall_any@{k}"] = bool(relevant & top)
        out[f"recall_all@{k}"] = relevant <= top
    out[f"ndcg@{NDCG_K}"] = round(ndcg(ranked, relevant), 4)
    return out


def evaluate(mem: Memory, q: dict) -> dict:
    t0 = time.perf_counter()
    present = {str(s) for s in q["haystack_session_ids"]}
    named = [str(s) for s in q.get("answer_session_ids") or []]
    want_sessions = {s for s in named if s in present}
    evidence, _ = load_question(mem, q, evidence_sessions=want_sessions)
    want_turns = set(evidence)
    ns = mem.namespace("q")
    mem.embed_pending(ns, limit=10**9)
    mem.flush()
    load_s = time.perf_counter() - t0
    as_of = timeutil.format(parse_date(q["question_date"]) + 59_999)
    body = {"op": "query", "namespace": "q", "text": q["question"], "as_of": as_of, "top_k": MAX_TOP_K,
            "max_tokens": NO_BUDGET}  # fmt: skip
    t1 = time.perf_counter()
    resp = mem.handle(body)
    query_ms = (time.perf_counter() - t1) * 1000
    sessions = distinct(item["thread_id"] for item in resp["items"])
    turns = distinct(item["source"]["id"] for item in resp["items"])
    return {
        "question_id": q["question_id"],
        "question_type": q.get("question_type"),
        "abstention": is_abstention(q["question_id"]),
        "sessions": len(present),
        "evidence_sessions": len(want_sessions),
        "evidence_sessions_missing": len(set(named) - present),
        "evidence_turns": len(want_turns),
        "items_returned": len(resp["items"]),
        "sessions_ranked": len(sessions),
        "session": score(sessions, want_sessions) if want_sessions else None,
        "turn": score(turns, want_turns) if want_turns else None,
        "ranked_sessions": sessions[:KEEP_RANKED],
        "load_s": round(load_s, 3),
        "query_ms": round(query_ms, 2),
    }


def level_metrics(rows: list[dict], level: str) -> dict:
    """Means over the questions scored at this level ("session" or "turn")."""
    scored = [r[level] for r in rows if r.get(level)]
    out: dict = {"n": len(scored)}
    if not scored:
        return out
    n = len(scored)
    for kind in ("any", "all"):
        for k in KS:
            key = f"recall_{kind}@{k}"
            out[key] = round(sum(s[key] for s in scored) / n, 4)
    out[f"ndcg@{NDCG_K}"] = round(sum(s[f"ndcg@{NDCG_K}"] for s in scored) / n, 4)
    out["mrr"] = round(sum(1 / s["rank"] for s in scored if s["rank"]) / n, 4)
    return out


def groups(rows: list[dict]) -> dict[str, list[dict]]:
    return {"all": rows, "answerable": [r for r in rows if not r["abstention"]],
            "abstention": [r for r in rows if r["abstention"]]}  # fmt: skip


def summarize(rows: list[dict]) -> dict:
    sets = groups(rows)
    summary: dict = {
        "questions": len(rows),
        "skipped_no_evidence": sum(1 for r in rows if not r["session"]),
        "evidence_sessions_missing": sum(r["evidence_sessions_missing"] for r in rows),
        f"fewer_than_{max(KS)}_sessions_ranked": sum(1 for r in rows if r["sessions_ranked"] < min(max(KS), r["sessions"])),
    }
    for name, rs in sets.items():
        summary[name] = {"session": level_metrics(rs, "session"), "turn": level_metrics(rs, "turn")}
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in sets["answerable"]:
        by_type[r.get("question_type") or "unknown"].append(r)
    order = [t for t in TYPES if t in by_type] + sorted(t for t in by_type if t not in TYPES)
    summary["by_type"] = {t: {"session": level_metrics(by_type[t], "session"), "turn": level_metrics(by_type[t], "turn")}
                          for t in order}  # fmt: skip
    loads = sorted(r["load_s"] for r in rows)
    times = sorted(r["query_ms"] for r in rows)
    if rows:
        summary["load_s"] = {"median": loads[len(loads) // 2], "total": round(sum(loads), 1)}
        summary["query_ms"] = {"median": times[len(times) // 2], "p95": times[int(0.95 * (len(times) - 1))]}
    return summary


def table(summary: dict, meta: dict) -> str:
    """The compact table printed at the end of a run."""
    keys = [f"recall_any@{k}" for k in KS] + ["recall_all@5", "recall_all@10", f"ndcg@{NDCG_K}", "mrr"]
    heads = [f"R@{k}" for k in KS] + ["all@5", "all@10", f"NDCG@{NDCG_K}", "MRR"]
    config = meta.get("config", {})
    title = (f"LongMemEval retrieval: search {config.get('search')}, model {meta.get('model') or 'none'}, "
             f"{summary['questions']} questions, {meta.get('wall_s', 0):.0f} s")  # fmt: skip
    lines = [title]
    labelled = [("all questions", summary["all"]), ("answerable (no _abs)", summary["answerable"])]
    labelled += [(f"  {t}", m) for t, m in summary["by_type"].items()]
    labelled += [("abstention (_abs)", summary["abstention"])]
    for level in ("session", "turn"):
        lines.append("")
        lines.append(f"{level} level: R@k = an evidence {level} in the top k, all@k = every one (both in %)")
        lines.append(f"{'':28}{'n':>5}" + "".join(f"{h:>8}" for h in heads))
        for label, m in labelled:
            m = m[level]
            if not m["n"]:
                continue
            cells = "".join(f"{100 * m[k]:>8.1f}" if k.startswith("recall") else f"{m[k]:>8.3f}" for k in keys)
            lines.append(f"{label:28}{m['n']:>5}{cells}")
    lines.append("")
    short = summary.get(f"fewer_than_{max(KS)}_sessions_ranked", 0)
    timing = ""
    if "query_ms" in summary:
        timing = f"load median {summary['load_s']['median']:.2f} s, query median {summary['query_ms']['median']:.1f} ms; "
    lines.append(f"{timing}{summary['skipped_no_evidence']} questions without an evidence session; "
                 f"{short} with fewer than {max(KS)} sessions ranked")  # fmt: skip
    return "\n".join(lines)


def read_log(path: Path, settings: dict) -> tuple[dict[str, dict], str | None]:
    """The rows of an earlier run's --questions-out, or an error if it was made with other settings."""
    done: dict[str, dict] = {}
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if not lines:
        return done, None
    try:
        head = json.loads(lines[0]).get("settings")
    except ValueError:
        head = None
    if head != settings:
        return done, (f"{path} holds a run with other settings ({head}); this run has {settings}. "
                      "Use another --questions-out file.")  # fmt: skip
    for line in lines[1:]:
        try:
            row = json.loads(line)
        except ValueError:  # a line cut short by an interrupted run
            continue
        done[str(row["question_id"])] = row
    return done, None


def cmd_run(args: argparse.Namespace) -> int:
    data_path = Path(args.data)
    questions = load(data_path)
    if args.limit:
        questions = questions[: args.limit]
    cfg = Config(search=args.search, doc_context=args.doc_context, doc_author=args.doc_author)
    embedder, rt = (None, None) if args.search == "keyword" else make_embedder(
        args.embedder, Path(args.root).expanduser() if args.root else None
    )
    meta = record(embedder.name if embedder is not None else None)
    config = {"search": cfg.search, "doc_context": cfg.doc_context, "doc_author": cfg.doc_author}
    meta.update({"dataset": str(data_path), "dataset_sha256": sha256_file(data_path), "config": config,
                 "top_k": MAX_TOP_K, "as_of": "the question date"})  # fmt: skip
    settings = {"dataset_sha256": meta["dataset_sha256"], "model": meta["model"], **config}
    log_path = Path(args.questions_out) if args.questions_out else None
    done: dict[str, dict] = {}
    if log_path is not None:
        done, error = read_log(log_path, settings)
        if error:
            print(error, file=sys.stderr)
            if rt is not None:
                rt.stop()
            return 2
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists() or not log_path.stat().st_size:
            log_path.write_text(json.dumps({"settings": settings}) + "\n", encoding="utf-8")
    rows: list[dict] = []
    resumed = 0
    t0 = time.perf_counter()
    try:
        with open(log_path, "a", encoding="utf-8") if log_path else contextlib.nullcontext() as log:
            for i, q in enumerate(questions):
                row = done.get(str(q["question_id"]))
                if row is not None:
                    resumed += 1
                else:
                    with Memory(None, embedder=embedder, config=cfg, cache_path=args.cache, embed_batch=args.batch) as mem:
                        row = evaluate(mem, q)
                    if log is not None:
                        log.write(json.dumps(row) + "\n")
                        log.flush()
                rows.append(row)
                if args.verbose or (i + 1) % 10 == 0 or i + 1 == len(questions):
                    s = summarize(rows)["all"]["session"]
                    print(f"[{i + 1}/{len(questions)}] R@5 {s.get('recall_any@5', 0):.3f}  R@10 {s.get('recall_any@10', 0):.3f}"
                          f"  all@10 {s.get('recall_all@10', 0):.3f}  ({time.perf_counter() - t0:.0f} s)", file=sys.stderr)  # fmt: skip
    finally:
        if rt is not None:
            rt.stop()
    meta["finished_utc"] = utc_now()
    meta["wall_s"] = round(time.perf_counter() - t0, 1)
    meta["resumed_questions"] = resumed
    summary = summarize(rows)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"meta": meta, "summary": summary, "per_question": rows}, indent=2))
    print(table(summary, meta))
    return 0


def metric_value(row: dict, metric: str) -> float | None:
    """``session_recall_any@5`` -> row["session"]["recall_any@5"] (None when the question is not scored there)."""
    level, _, name = metric.partition("_")
    scores = row.get(level)
    if not scores or name not in scores:
        return None
    return float(scores[name])


def cmd_compare(args: argparse.Namespace) -> int:
    a = json.loads(Path(args.a).read_text())
    b = json.loads(Path(args.b).read_text())
    if a["meta"].get("dataset_sha256") != b["meta"].get("dataset_sha256"):
        print("warning: the two results used different dataset files", file=sys.stderr)
    ra = {str(r["question_id"]): r for r in groups(a["per_question"])[args.set]}
    rb = {str(r["question_id"]): r for r in groups(b["per_question"])[args.set]}
    out: dict = {
        "set": args.set,
        "a": {"file": args.a, "search": a["meta"].get("config", {}).get("search"), "model": a["meta"].get("model")},
        "b": {"file": args.b, "search": b["meta"].get("config", {}).get("search"), "model": b["meta"].get("model")},
        "metrics": {},
    }
    for metric in [m.strip() for m in args.metrics.split(",") if m.strip()]:
        common = [q for q in ra if q in rb and metric_value(ra[q], metric) is not None
                  and metric_value(rb[q], metric) is not None]  # fmt: skip
        if not common:
            out["metrics"][metric] = {"questions": 0}
            continue
        xa = [metric_value(ra[q], metric) for q in common]
        xb = [metric_value(rb[q], metric) for q in common]
        mean, lo, hi = paired_bootstrap(xa, xb, args.bootstrap, args.seed)
        out["metrics"][metric] = {"questions": len(common), "a": round(sum(xa) / len(xa), 4),
                                  "b": round(sum(xb) / len(xb), 4), "difference_points": round(100 * mean, 2),
                                  "ci95_points": [round(100 * lo, 2), round(100 * hi, 2)]}  # fmt: skip
    print(json.dumps(out, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cogito-mem eval longmemeval-recall", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("compare", help="paired differences of two runs (b - a) with 95 %% bootstrap intervals")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--metrics", default=COMPARE_METRICS,
                   help=f"comma-separated, LEVEL_METRIC as in the per-question rows (default: {COMPARE_METRICS})")  # fmt: skip
    c.add_argument("--set", default="all", choices=SETS, help="which questions (default: all)")
    c.add_argument("--bootstrap", type=int, default=10_000)
    c.add_argument("--seed", type=int, default=0)
    c.set_defaults(func=cmd_compare)
    p.add_argument("--data", help="longmemeval_s_cleaned.json (or any LongMemEval file)")
    p.add_argument("--search", default="hybrid", choices=["hybrid", "vector", "keyword"])
    p.add_argument("--doc-context", default="previous", choices=["own", "previous"])
    p.add_argument("--doc-author", action=argparse.BooleanOptionalAction, default=True,
                   help="put the role before each turn's text, as the memory does by default (default: on)")  # fmt: skip
    p.add_argument("--embedder", default="auto", choices=["auto", "hash"], help="hash: pipeline checks only")
    p.add_argument("--cache", default=str(Path.home() / ".cogito-mem" / "cache" / "embeddings.sqlite3"))
    p.add_argument("--root", help="where llama.cpp and the model live (default ~/.cogito-mem)")
    p.add_argument("--batch", type=int, default=32, help="inputs per embedding request")
    p.add_argument("--limit", type=int, help="first N questions only")
    p.add_argument("--questions-out", help="write each question's outcome here as it finishes (JSON lines); "
                   "rerun with the same file to resume")  # fmt: skip
    p.add_argument("--out", help="write the summary and every per-question outcome here (JSON)")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.func is cmd_run and not args.data:
        build_parser().error("--data is required")
    return int(args.func(args) or 0)
