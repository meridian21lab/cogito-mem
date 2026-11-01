"""Recall on histories past 1M tokens, where no single request can hold the whole conversation.

    cogito-mem eval long-history run --data longmemeval_m_cleaned.json --out results/long-history/m.json
    cogito-mem eval long-history run --data longmemeval_m_cleaned.json --sessions 50 --split tuning --out s50.json
    cogito-mem eval long-history answer --contexts m-contexts.jsonl --arm search-5000 --env-file .env --out a.json
    cogito-mem eval long-history agent --data longmemeval_m_cleaned.json --split tuning --env-file .env --out g.json
    cogito-mem eval long-history compare a.json b.json --metric search.base.coverage.1000

LongMemEval_M gives each of its 500 questions about 480 chat sessions, 1.13-1.30M tokens by
chars/4, with the sessions and turns that hold the answer labelled. Each question gets a fresh
memory and everything below is asked of it in one pass, so a variant costs milliseconds and not
a reload:

- **Search** (what ``memory_query`` returns): session R@k and all@k; for each budget the share of
  questions with every evidence turn in the reply (coverage) and with at least one (reached).
  Each ``--variants`` name is one search setting (``VARIANTS``), all over the same loaded memory.
- **Delivery** (what reaches Claude unasked): each ``recall.DESIGNS`` run through the real hook
  code, with whether it fired, what it reached and how many tokens it took. The ``pointers``
  design also counts as reached what its lines point at, which Claude must still open.
- **Recency**: the last N tokens of the history with no memory, the baseline for a budget.

Everything is scored twice: ``question`` searches as of the question date, as it would be in use,
and ``none`` has no date cutoff, LongMemEval's own protocol and the one rivals publish. A cutoff can
hide evidence dated later the same day, so ``none`` is the higher of the two.

``--sessions N`` keeps the evidence sessions and a random N - k of the others (seeded per
question), which gives the same questions at growing sizes. ``--split`` takes the tuning (30 %)
or held-out (70 %) questions by a hash of the id: choose settings on tuning, report held-out.
``--contexts-out`` keeps the text each arm returned, for ``answer``.

``answer`` has a model answer from one arm's text and LongMemEval's judge prompts grade it.
``agent`` gives the model the real ``memory_query`` and ``memory_open`` tools and each recall design's
hook text, so it measures the whole path: did it search, did it open, did it answer correctly.
Abstention questions (``_abs``) are scored by retrieval only when they name an answer session.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

from .. import recall, timeutil
from ..api import DEFAULT_TOP_K
from ..mcp_server import INSTRUCTIONS as MCP_INSTRUCTIONS
from ..mcp_server import _tools as mcp_tools
from ..memory import Config, Memory
from ..tokenizer import count
from .common import query_past_top_k_limit, record, sha256_file, utc_now
from .longmemeval import NO_BUDGET, load, load_question, make_embedder, paired_bootstrap, parse_date
from .longmemeval_recall import distinct, read_log, score

BUDGETS = (300, 1000, 2500, 5000)
CUTOFFS = ("question", "none")
RANKED_TURNS = 300
TUNING_SHARE = 30
NS = "q"

# Search settings compared over the same loaded memory; each is applied at query time.
VARIANTS: dict[str, dict] = {
    "base": {},
    "exact": {"exact_lane": True},
    "session": {"session_boost": 0.5},
    "exact+session": {"exact_lane": True, "session_boost": 0.5},
}


def split_of(question_id: object) -> str:
    bucket = int(hashlib.sha256(str(question_id).encode()).hexdigest(), 16) % 100
    return "tuning" if bucket < TUNING_SHARE else "heldout"


def subset(q: dict, n: int | None, seed: int = 0) -> dict:
    """The question with its evidence sessions and a random ``n`` - k others, in their original order."""
    ids = [str(s) for s in q["haystack_session_ids"]]
    if n is None or n >= len(ids):
        return q
    answers = {str(s) for s in q.get("answer_session_ids") or []}
    others = [i for i, s in enumerate(ids) if s not in answers]
    room = max(0, n - (len(ids) - len(others)))
    rng = random.Random(f"{seed}:{q['question_id']}")
    keep = set(rng.sample(others, min(room, len(others)))) | {i for i, s in enumerate(ids) if s in answers}
    order = sorted(keep)
    return {
        **q,
        "haystack_session_ids": [q["haystack_session_ids"][i] for i in order],
        "haystack_dates": [q["haystack_dates"][i] for i in order],
        "haystack_sessions": [q["haystack_sessions"][i] for i in order],
    }


class EvalClient:
    """What the recall hook needs from a client, over a loaded memory and a fixed ``as_of``."""

    def __init__(self, mem: Memory, as_of: str | None):
        self.mem = mem
        self.as_of = as_of

    def query(self, text: str, namespace: str | None = None, **kwargs) -> dict:
        body = {"op": "query", "namespace": NS, "text": text, **kwargs}
        if self.as_of is not None:
            body["as_of"] = self.as_of
        return self.mem.handle(body)


def reach(want: set[str], items: list[dict]) -> dict:
    got = {it["source"]["id"] for it in items}
    return {"any": bool(want & got), "all": bool(want) and want <= got}


def search_arm(mem: Memory, q: dict, want_turns: set[str], want_sessions: set[str], as_of: str | None) -> dict:
    """One search setting at one cutoff: the rankings, and each budget's reply."""
    body = {"op": "query", "namespace": NS, "text": q["question"], "top_k": DEFAULT_TOP_K}
    if as_of is not None:
        body["as_of"] = as_of
    resp = query_past_top_k_limit(mem, {**body, "top_k": RANKED_TURNS, "max_tokens": NO_BUDGET})
    sessions = distinct(item["thread_id"] for item in resp["items"])
    turns = distinct(item["source"]["id"] for item in resp["items"])
    out: dict = {
        "session": score(sessions, want_sessions) if want_sessions else None,
        "turn": score(turns, want_turns) if want_turns else None,
        "evidence_ranks": sorted(turns.index(t) + 1 for t in want_turns if t in turns),
        "budgets": {},
    }
    for n in BUDGETS:
        reply = mem.handle({**body, "max_tokens": n})
        out["budgets"][str(n)] = {**reach(want_turns, reply["items"]), "tokens": reply["tokens"]}
    return out


def recency_items(mem: Memory, budget: int, as_of_ms: int | None) -> list[dict]:
    """The newest messages that fit the budget, oldest first: what reading the tail of the history gives."""
    ns = mem.namespace(NS)
    items: list[dict] = []
    used = 0
    for msg in reversed(ns.messages):
        if as_of_ms is not None and msg.valid > as_of_ms:
            continue
        n = count(mem.tokenizer, msg.text)
        if used + n > budget:
            break
        used += n
        items.append({"text": msg.text, "author": msg.author, "valid_at": timeutil.format(msg.valid),
                      "thread_id": msg.thread_id, "source": {"id": msg.id}})  # fmt: skip
    return items[::-1]


def delivery_arm(mem: Memory, q: dict, want_turns: set[str], want_sessions: set[str], as_of: str | None, design: str) -> dict:
    hook = {"prompt": q["question"], "session_id": "the-session-asking", "cwd": None}
    shot = recall.DESIGNS[design](EvalClient(mem, as_of), hook, NS)
    sessions = {it["thread_id"] for it in shot.items}
    return {
        "fired": bool(shot.text),
        **reach(want_turns, shot.items),
        "session_any": bool(want_sessions & sessions),
        "tokens": count(mem.tokenizer, shot.text) if shot.text else 0,
        "lines": len(shot.items),
    }


def evaluate(mem: Memory, q: dict, variants: dict[str, Config], contexts=None) -> dict:
    t0 = time.perf_counter()
    present = {str(s) for s in q["haystack_session_ids"]}
    want_sessions = {str(s) for s in q.get("answer_session_ids") or []} & present
    evidence, _ = load_question(mem, q, evidence_sessions=want_sessions)
    want_turns = set(evidence)
    ns = mem.namespace(NS)
    mem.embed_pending(ns, limit=10**9)
    mem.flush()
    load_s = time.perf_counter() - t0
    date_ms = parse_date(q["question_date"]) + 59_999
    cutoffs = {"question": timeutil.format(date_ms), "none": None}
    t1 = time.perf_counter()
    row: dict = {
        "question_id": q["question_id"],
        "question_type": q.get("question_type"),
        "abstention": "_abs" in str(q["question_id"]),
        "sessions": len(present),
        "messages": len(ns.messages),
        "history_chars": sum(len(m.text) for m in ns.messages),
        "evidence_sessions": len(want_sessions),
        "evidence_turns": len(want_turns),
        "search": {},
        "delivery": {},
        "recency": {},
    }
    shipped = mem.config
    for name, cfg in variants.items():
        mem.config = cfg
        row["search"][name] = {c: search_arm(mem, q, want_turns, want_sessions, as_of) for c, as_of in cutoffs.items()}
    mem.config = shipped
    for design in recall.DESIGNS:
        row["delivery"][design] = {c: delivery_arm(mem, q, want_turns, want_sessions, as_of, design)
                                   for c, as_of in cutoffs.items()}  # fmt: skip
    for n in BUDGETS:
        row["recency"][str(n)] = {c: reach(want_turns, recency_items(mem, n, date_ms if c == "question" else None))
                                  for c in CUTOFFS}  # fmt: skip
    row["query_s"] = round(time.perf_counter() - t1, 3)
    row["load_s"] = round(load_s, 3)
    if contexts is not None:
        contexts.write(json.dumps(context_row(mem, q, cutoffs["question"], date_ms, want_sessions)) + "\n")
        contexts.flush()
    return row


def context_row(mem: Memory, q: dict, as_of: str, date_ms: int, want_sessions: set[str]) -> dict:
    """The text each answerable arm returned, for ``answer``."""
    arms: dict[str, list[dict]] = {}
    body = {"op": "query", "namespace": NS, "text": q["question"], "as_of": as_of, "top_k": DEFAULT_TOP_K}
    for n in (1000, 5000):
        arms[f"search-{n}"] = [_keep(it) for it in mem.handle({**body, "max_tokens": n})["items"]]
        arms[f"recency-{n}"] = [_keep(it) for it in recency_items(mem, n, date_ms)]
    for design in recall.DESIGNS:
        shot = recall.DESIGNS[design](EvalClient(mem, as_of), {"prompt": q["question"], "session_id": "the-session-asking"}, NS)
        arms[f"hook-{design}"] = [{"text": shot.text, "valid_at": as_of, "author": "memory"}] if shot.text else []
    ns = mem.namespace(NS)
    arms["oracle"] = [
        {"text": m.text, "valid_at": timeutil.format(m.valid), "author": m.author}
        for m in ns.messages
        if m.thread_id in want_sessions
    ]
    return {
        "question_id": q["question_id"],
        "question_type": q.get("question_type"),
        "question": q["question"],
        "question_date": q["question_date"],
        "answer": q.get("answer"),
        "arms": arms,
    }


def _keep(item: dict) -> dict:
    return {"text": item["text"], "valid_at": item["valid_at"], "author": item["author"]}


# --------------------------------------------------------------------------- summary


def _share(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize(rows: list[dict], n_boot: int = 0) -> dict:
    answerable = [r for r in rows if not r["abstention"] and r["evidence_turns"]]
    out: dict = {
        "questions": len(rows),
        "answerable_with_labels": len(answerable),
        "history_chars_per_4": _spread([r["history_chars"] // 4 for r in rows]),
        "sessions": _spread([r["sessions"] for r in rows]),
    }
    out["all"] = _summary_of(answerable)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in answerable:
        by_type[r.get("question_type") or "unknown"].append(r)
    out["by_type"] = {t: {"n": len(rs), **_summary_of(rs)} for t, rs in sorted(by_type.items())}
    loads = sorted(r["load_s"] for r in rows)
    if loads:
        out["load_s_median"] = loads[len(loads) // 2]
    return out


def _spread(values: list[int]) -> dict:
    if not values:
        return {}
    values = sorted(values)
    return {"min": values[0], "median": values[len(values) // 2], "max": values[-1]}


def _summary_of(rows: list[dict]) -> dict:
    out: dict = {"search": {}, "delivery": {}, "recency": {}}
    if not rows:
        return out
    for name in rows[0]["search"]:
        out["search"][name] = {}
        for c in CUTOFFS:
            arms = [r["search"][name][c] for r in rows]
            sess = [a["session"] for a in arms if a["session"]]
            cell: dict = {
                "session": {k: _share([s[k] for s in sess]) for k in
                            ("recall_any@1", "recall_any@5", "recall_any@10", "recall_all@5", "recall_all@10")},  # fmt: skip
                "coverage": {b: _share([a["budgets"][b]["all"] for a in arms]) for b in map(str, BUDGETS)},
                "reached": {b: _share([a["budgets"][b]["any"] for a in arms]) for b in map(str, BUDGETS)},
            }
            out["search"][name][c] = cell
    for design in rows[0]["delivery"]:
        out["delivery"][design] = {}
        for c in CUTOFFS:
            arms = [r["delivery"][design][c] for r in rows]
            out["delivery"][design][c] = {
                "fired": _share([a["fired"] for a in arms]),
                "any": _share([a["any"] for a in arms]),
                "all": _share([a["all"] for a in arms]),
                "session_any": _share([a["session_any"] for a in arms]),
                "tokens_when_fired": _mean([a["tokens"] for a in arms if a["fired"]]),
            }
    for n in map(str, BUDGETS):
        out["recency"][n] = {c: {"all": _share([r["recency"][n][c]["all"] for r in rows]),
                                 "any": _share([r["recency"][n][c]["any"] for r in rows])} for c in CUTOFFS}  # fmt: skip
    return out


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 1) if xs else None


def table(summary: dict, meta: dict) -> str:
    size = summary["history_chars_per_4"]
    lines = [f"{meta['dataset']}: {summary['answerable_with_labels']} answerable of {summary['questions']} questions, "
             f"history {size.get('min')}/{size.get('median')}/{size.get('max')} tokens (chars/4), "
             f"sessions {summary['sessions'].get('median')}, {meta.get('wall_s', 0):.0f} s"]  # fmt: skip
    whole = summary["all"]
    for c in CUTOFFS:
        lines += ["", f"cutoff {c}", f"{'':22}{'R@1':>7}{'R@5':>7}{'R@10':>7}{'all@10':>8}"
                  + "".join(f"{'cov' + b:>9}" for b in map(str, BUDGETS))]  # fmt: skip
        for name, cell in whole["search"].items():
            s, cov = cell[c]["session"], cell[c]["coverage"]
            lines.append(f"{'search ' + name:22}{_pc(s['recall_any@1']):>7}{_pc(s['recall_any@5']):>7}"
                         f"{_pc(s['recall_any@10']):>7}{_pc(s['recall_all@10']):>8}"
                         + "".join(f"{_pc(cov[b]):>9}" for b in map(str, BUDGETS)))  # fmt: skip
        lines.append(f"{'recency':22}{'':>29}" + "".join(f"{_pc(whole['recency'][b][c]['all']):>9}" for b in map(str, BUDGETS)))
        for design, cell in whole["delivery"].items():
            d = cell[c]
            lines.append(f"hook {design:17} fired {_pc(d['fired'])}  turn any {_pc(d['any'])}  all {_pc(d['all'])}  "
                         f"session {_pc(d['session_any'])}  tokens {d['tokens_when_fired']}")  # fmt: skip
    return "\n".join(lines)


def _pc(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.1f}"


# --------------------------------------------------------------------------- run


def cmd_run(args: argparse.Namespace) -> int:
    data_path = Path(args.data)
    questions = load(data_path)
    if args.split:
        questions = [q for q in questions if split_of(q["question_id"]) == args.split]
    if args.limit:
        questions = questions[: args.limit]
    names = [v.strip() for v in args.variants.split(",") if v.strip()]
    cfg = Config(search=args.search)
    variants = {name: dataclasses.replace(cfg, **VARIANTS[name]) for name in names}
    embedder, rt = (None, None) if args.search == "keyword" else make_embedder(args.embedder, None)
    meta = record(embedder.name if embedder is not None else None)
    meta.update({"dataset": str(data_path), "dataset_sha256": sha256_file(data_path), "search": args.search,
                 "variants": {n: VARIANTS[n] for n in names}, "designs": list(recall.DESIGNS),
                 "sessions": args.sessions, "split": args.split, "seed": args.seed})  # fmt: skip
    settings = {"dataset_sha256": meta["dataset_sha256"], "model": meta["model"], "search": args.search,
                "variants": meta["variants"], "designs": meta["designs"], "sessions": args.sessions, "seed": args.seed}  # fmt: skip
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
    t0 = time.perf_counter()
    try:
        with open(log_path, "a", encoding="utf-8") if log_path else contextlib.nullcontext() as log, \
                open(args.contexts_out, "a", encoding="utf-8") if args.contexts_out else contextlib.nullcontext() as contexts:  # fmt: skip
            for i, q in enumerate(questions):
                row = done.get(str(q["question_id"]))
                if row is None:
                    with Memory(None, embedder=embedder, config=cfg, cache_path=args.cache, embed_batch=args.batch) as mem:
                        row = evaluate(mem, subset(q, args.sessions, args.seed), variants, contexts)
                    if log is not None:
                        log.write(json.dumps(row) + "\n")
                        log.flush()
                rows.append(row)
                if args.verbose or (i + 1) % 10 == 0 or i + 1 == len(questions):
                    print(f"[{i + 1}/{len(questions)}] {time.perf_counter() - t0:.0f} s", file=sys.stderr)
    finally:
        if rt is not None:
            rt.stop()
    meta["finished_utc"] = utc_now()
    meta["wall_s"] = round(time.perf_counter() - t0, 1)
    summary = summarize(rows)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"meta": meta, "summary": summary, "per_question": rows}))
    print(table(summary, meta))
    return 0


# --------------------------------------------------------------------------- compare


def metric_value(row: dict, metric: str, cutoff: str) -> float | None:
    """``search.base.coverage.1000``, ``search.base.session.recall_any@5``, ``delivery.pointers.any``,
    ``recency.1000.all``, or ``J`` for an ``answer`` result."""
    if metric == "J":
        return None if row.get("judged") is None else float(row["judged"])
    parts = metric.split(".")
    if parts[0] == "search":
        arm = row["search"][parts[1]][cutoff]
        if parts[2] in ("coverage", "reached"):
            return float(arm["budgets"][parts[3]]["all" if parts[2] == "coverage" else "any"])
        scored = arm.get(parts[2])
        return None if not scored else float(scored[parts[3]])
    if parts[0] == "delivery":
        return float(row["delivery"][parts[1]][cutoff][parts[2]])
    if parts[0] == "recency":
        return float(row["recency"][parts[1]][cutoff][parts[2]])
    raise ValueError(f"unknown metric {metric}")


def cmd_compare(args: argparse.Namespace) -> int:
    a = json.loads(Path(args.a).read_text())
    b = json.loads(Path(args.b).read_text()) if args.b else a
    metric_b = args.metric_b or args.metric
    ra = {str(r["question_id"]): r for r in a["per_question"]}
    rb = {str(r["question_id"]): r for r in b["per_question"]}
    xa: list[float] = []
    xb: list[float] = []
    for q in sorted(set(ra) & set(rb)):
        if args.metric != "J" and (ra[q]["abstention"] or not ra[q]["evidence_turns"]):
            continue
        va, vb = metric_value(ra[q], args.metric, args.cutoff), metric_value(rb[q], metric_b, args.cutoff)
        if va is not None and vb is not None:
            xa.append(va)
            xb.append(vb)
    if not xa:
        print("no questions in common", file=sys.stderr)
        return 1
    mean, lo, hi = paired_bootstrap(xa, xb, args.bootstrap, args.seed)
    print(json.dumps({"questions": len(xa), "a": {"metric": args.metric, "value": round(sum(xa) / len(xa), 4)},
                      "b": {"metric": metric_b, "value": round(sum(xb) / len(xb), 4)},
                      "difference_points": round(100 * mean, 2),
                      "ci95_points": [round(100 * lo, 2), round(100 * hi, 2)]}, indent=2))  # fmt: skip
    return 0


# --------------------------------------------------------------------------- answer

JUDGE_BASE = (
    "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response "
    "contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or "
    "contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only "
    "contains a subset of the information required by the answer, answer no."
)
JUDGE_EXTRA = {
    "temporal-reasoning": (
        " In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number "
        "of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer "
        "is 18), the model's response is still correct."
    ),
    "knowledge-update": (
        " If the response contains some previous information along with an updated answer, the response should be "
        "considered as correct as long as the updated answer is the required answer."
    ),
}
JUDGE_PREFERENCE = (
    "I will give you a question, a rubric for desired personalized response, and a response from a model. Please "
    "answer yes if the response satisfies the desired response. Otherwise, answer no. The model does not need to "
    "reflect all the points in the rubric. The response is correct as long as it recalls and utilizes the user's "
    "personal information correctly."
)
JUDGE_ABSTENTION = (
    "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes if the "
    "model correctly identifies the question as unanswerable. The model could say that the information is incomplete, or some "
    "other information is given but the asked information is not."
)
ANSWER_PROMPT = """I will give you several notes from past conversations between you and a user, each with the time it was said. Please answer the question based on the relevant notes. If the question cannot be answered from them, say so.

Notes:
{notes}

Current date: {date}
Question: {question}
Answer:"""


def judge_prompt(row: dict, response: str) -> str:
    kind = row.get("question_type")
    if "_abs" in str(row["question_id"]):
        return (f"{JUDGE_ABSTENTION}\n\nQuestion: {row['question']}\n\nExplanation: {row['answer']}\n\n"
                f"Model Response: {response}\n\nDoes the model correctly identify the question as unanswerable? "
                "Answer yes or no only.")  # fmt: skip
    if kind == "single-session-preference":
        return (f"{JUDGE_PREFERENCE}\n\nQuestion: {row['question']}\n\nRubric: {row['answer']}\n\n"
                f"Model Response: {response}\n\nIs the model response correct? Answer yes or no only.")  # fmt: skip
    return (f"{JUDGE_BASE}{JUDGE_EXTRA.get(kind, '')}\n\nQuestion: {row['question']}\n\nCorrect Answer: {row['answer']}\n\n"
            f"Model Response: {response}\n\nIs the model response correct? Answer yes or no only.")  # fmt: skip


def grade(llm, args: argparse.Namespace, row: dict, response: str) -> bool | None:
    verdict = llm.chat(args.judge_model, [{"role": "user", "content": judge_prompt(row, response)}],
                       max_tokens=args.judge_max_tokens, temperature=None, reasoning=args.judge_reasoning)  # fmt: skip
    word = verdict["content"].strip().lower()
    return word.startswith("yes") if word else None


def make_llm(args: argparse.Namespace, LLM, read_env_file):
    env = read_env_file(Path(args.env_file))
    key = env.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_AUTH_TOKEN")
    if not key:
        raise SystemExit(f"no OPENROUTER_API_KEY in {args.env_file}")
    return LLM(env.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api", key, Path(args.llm_cache).expanduser())


def notes_text(items: list[dict]) -> str:
    return "\n".join(f"[{it['valid_at']}, {it['author']}] {it['text']}" for it in items)


def cmd_answer(args: argparse.Namespace) -> int:
    from concurrent.futures import ThreadPoolExecutor

    from .locomo_qa import LLM, read_env_file

    llm = make_llm(args, LLM, read_env_file)
    rows = [json.loads(line) for line in Path(args.contexts).read_text().splitlines() if line.strip()]
    if args.split:
        rows = [r for r in rows if split_of(r["question_id"]) == args.split]
    if args.limit:
        rows = rows[: args.limit]

    def one(row: dict) -> dict:
        items = row["arms"].get(args.arm)
        if items is None:
            raise KeyError(f"no arm {args.arm} in {args.contexts}")
        notes = notes_text(items) or "(none)"
        answer = llm.chat(args.answer_model, [{"role": "user", "content": ANSWER_PROMPT.format(
            notes=notes, date=row["question_date"], question=row["question"])}],
            max_tokens=args.answer_max_tokens, temperature=None if args.no_temperature else 0.0,
            reasoning=args.answer_reasoning)  # fmt: skip
        return {
            "question_id": row["question_id"],
            "question_type": row.get("question_type"),
            "abstention": "_abs" in str(row["question_id"]),
            "evidence_turns": 1,
            "judged": grade(llm, args, row, answer["content"]),
            "context_tokens": len(notes) // 4,
            "prompt_tokens": (answer.get("usage") or {}).get("prompt_tokens"),
            "answer": answer["content"],
        }

    with ThreadPoolExecutor(args.workers) as pool:
        out = list(pool.map(one, rows))
    judged = [r for r in out if r["judged"] is not None]
    by_type: dict[str, list[bool]] = defaultdict(list)
    for r in judged:
        by_type[r["question_type"] or "unknown"].append(r["judged"])
    summary = {
        "questions": len(out),
        "J": round(100 * sum(r["judged"] for r in judged) / max(len(judged), 1), 2),
        "by_type": {t: {"n": len(v), "J": round(100 * sum(v) / len(v), 2)} for t, v in sorted(by_type.items())},
        "unjudged": len(out) - len(judged),
        "mean_context_tokens": round(sum(r["context_tokens"] for r in out) / max(len(out), 1), 1),
        "llm_cost_usd": round(llm.cost, 3),
    }
    meta = record(None)
    meta.update({"contexts": args.contexts, "arm": args.arm, "answer_model": args.answer_model, "judge_model": args.judge_model})
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"meta": meta, "summary": summary, "per_question": out}))
    print(json.dumps(summary, indent=2))
    return 0


# --------------------------------------------------------------------------- agent

AGENT_TOOLS = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}}
    for t in mcp_tools()
    if t["name"] in ("memory_query", "memory_open")
]
AGENT_SYSTEM = (
    "You are a coding and research assistant. You have no memory of earlier sessions except through the tools.\n\n"
    + MCP_INSTRUCTIONS
    + "\n\nAnswer the user's question in one short paragraph."
)


def run_agent(llm, args: argparse.Namespace, mem: Memory, q: dict, as_of: str, context: str | None) -> dict:
    """The answering model with the real tools over this question's memory: what it asks for, and what it answers."""
    prompt = f"(Current date: {q['question_date']})\n{q['question']}"
    if context:
        prompt = f"{context}\n\n{prompt}"
    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM}, {"role": "user", "content": prompt}]
    queries = opens = prompt_tokens = 0
    read: list[str] = []
    answer = ""
    for _ in range(args.max_steps):
        out = llm.chat(args.answer_model, messages, max_tokens=args.answer_max_tokens, temperature=0.0, tools=AGENT_TOOLS)
        prompt_tokens += (out.get("usage") or {}).get("prompt_tokens") or 0
        calls = out.get("tool_calls") or []
        if not calls:
            answer = out["content"]
            break
        messages.append({"role": "assistant", "content": out["content"] or "", "tool_calls": calls})
        for call in calls:
            fn = call["function"]
            try:
                params = json.loads(fn.get("arguments") or "{}")
                if fn["name"] == "memory_open":
                    opens += 1
                    allowed = {k: params[k] for k in ("id", "before", "after", "max_tokens") if k in params}
                    result = mem.handle({"op": "open", "namespace": NS, **allowed})
                    read += [it["id"] for it in result["items"]]
                else:
                    queries += 1
                    body = {"op": "query", "namespace": NS, "text": params["text"], "as_of": as_of,
                            "max_tokens": params.get("max_tokens", 1000)}  # fmt: skip
                    flt = {k: params[k] for k in ("valid_after", "valid_before") if params.get(k)}
                    if flt:
                        body["filter"] = flt
                    result = mem.handle(body)
                    read += [it["source"]["id"] for it in result["items"]]
                text = json.dumps(result, ensure_ascii=False)
            except Exception as exc:  # the model sees its mistake, as it would over MCP
                text = json.dumps({"error": str(exc)})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": text})
    return {"answer": answer, "queries": queries, "opens": opens, "prompt_tokens": prompt_tokens, "read": read}


def cmd_agent(args: argparse.Namespace) -> int:
    from concurrent.futures import ThreadPoolExecutor

    from .locomo_qa import LLM, read_env_file

    llm = make_llm(args, LLM, read_env_file)
    questions = load(Path(args.data))
    if args.split:
        questions = [q for q in questions if split_of(q["question_id"]) == args.split]
    if args.limit:
        questions = questions[: args.limit]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    embedder, rt = make_embedder("auto", None)
    log_path = Path(args.questions_out) if args.questions_out else None
    rows: dict[str, dict] = {}
    if log_path is not None and log_path.exists():
        for line in log_path.read_text().splitlines():
            row = json.loads(line)
            rows[f"{row['question_id']}|{row['arm']}"] = row

    def one(q: dict) -> list[dict]:
        todo = [a for a in arms if f"{q['question_id']}|{a}" not in rows]
        if not todo:
            return []
        out = []
        with Memory(None, embedder=embedder, config=Config(), cache_path=args.cache, embed_batch=args.batch) as mem:
            present = {str(s) for s in q["haystack_session_ids"]}
            want_sessions = {str(s) for s in q.get("answer_session_ids") or []} & present
            evidence, _ = load_question(mem, q, evidence_sessions=want_sessions)
            mem.embed_pending(mem.namespace(NS), limit=10**9)
            mem.flush()
            as_of = timeutil.format(parse_date(q["question_date"]) + 59_999)
            client = EvalClient(mem, as_of)
            hook = {"prompt": q["question"], "session_id": "the-session-asking"}
            for arm in todo:
                shot = recall.Shot() if arm == "tools-only" else recall.DESIGNS[arm](client, hook, NS)
                res = run_agent(llm, args, mem, q, as_of, shot.text)
                got = set(res.pop("read")) | {it["source"]["id"] for it in shot.items}
                ctx = {"question_id": q["question_id"], "question_type": q.get("question_type"), "question": q["question"],
                       "answer": q.get("answer")}  # fmt: skip
                out.append({
                    "question_id": q["question_id"], "question_type": q.get("question_type"), "arm": arm,
                    "abstention": "_abs" in str(q["question_id"]), "evidence_turns": len(evidence),
                    "judged": grade(llm, args, ctx, res["answer"]), "reached_any": bool(set(evidence) & got),
                    "reached_all": bool(evidence) and set(evidence) <= got, "fired": bool(shot.text), **res,
                })  # fmt: skip
        return out

    try:
        with ThreadPoolExecutor(args.workers) as pool, open(log_path, "a") if log_path else contextlib.nullcontext() as log:
            for i, batch in enumerate(pool.map(one, questions)):
                for row in batch:
                    rows[f"{row['question_id']}|{row['arm']}"] = row
                    if log is not None:
                        log.write(json.dumps(row) + "\n")
                        log.flush()
                if (i + 1) % 10 == 0:
                    print(f"[{i + 1}/{len(questions)}] ${llm.cost:.2f}", file=sys.stderr)
    finally:
        if rt is not None:
            rt.stop()
    summary: dict = {"cost_usd": round(llm.cost, 3)}
    for arm in arms:
        rs = [r for r in rows.values() if r["arm"] == arm]
        judged = [r for r in rs if r["judged"] is not None]
        summary[arm] = {
            "questions": len(rs),
            "J": round(100 * sum(r["judged"] for r in judged) / max(len(judged), 1), 2),
            "reached_any": _share([r["reached_any"] for r in rs if r["evidence_turns"]]),
            "searched": _share([r["queries"] > 0 for r in rs]),
            "opened": _share([r["opens"] > 0 for r in rs]),
            "fired": _share([r["fired"] for r in rs]),
            "prompt_tokens": _mean([r["prompt_tokens"] for r in rs]),
        }
    meta = record(embedder.name)
    meta.update({"dataset": args.data, "arms": arms, "answer_model": args.answer_model, "judge_model": args.judge_model})
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"meta": meta, "summary": summary, "per_question": list(rows.values())}))
    print(json.dumps(summary, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cogito-mem eval long-history", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="load each question's history and measure search and delivery over it")
    r.add_argument("--data", required=True)
    r.add_argument("--search", default="hybrid", choices=["hybrid", "vector", "keyword"])
    r.add_argument("--variants", default="base", help=f"comma-separated, of {', '.join(VARIANTS)}")
    r.add_argument("--sessions", type=int, help="keep the evidence sessions and random others up to this many")
    r.add_argument("--split", choices=["tuning", "heldout"])
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--embedder", default="auto", choices=["auto", "hash"], help="hash: pipeline checks only")
    r.add_argument("--cache", default=str(Path.home() / ".cogito-mem" / "cache" / "embeddings.sqlite3"))
    r.add_argument("--batch", type=int, default=32)
    r.add_argument("--limit", type=int)
    r.add_argument("--questions-out", help="each question's outcome as it finishes (JSON lines); rerun to resume")
    r.add_argument("--contexts-out", help="each question's arm texts (JSON lines), for `answer`")
    r.add_argument("--out")
    r.add_argument("--verbose", action="store_true")
    r.set_defaults(func=cmd_run)
    c = sub.add_parser("compare", help="paired difference (b - a) with a 95 %% bootstrap interval")
    c.add_argument("a")
    c.add_argument("b", nargs="?", help="default: the same file, with --metric-b")
    c.add_argument("--metric", default="search.base.coverage.1000")
    c.add_argument("--metric-b")
    c.add_argument("--cutoff", default="none", choices=CUTOFFS)
    c.add_argument("--bootstrap", type=int, default=10_000)
    c.add_argument("--seed", type=int, default=0)
    c.set_defaults(func=cmd_compare)
    a = sub.add_parser("answer", help="answer from one arm's text and grade with LongMemEval's judge prompts")
    a.add_argument("--contexts", required=True)
    a.add_argument("--arm", required=True)
    a.add_argument("--env-file", default=".env")
    a.add_argument("--answer-model", default="anthropic/claude-haiku-5.5")
    a.add_argument("--answer-reasoning")
    a.add_argument("--answer-max-tokens", type=int, default=2000)
    a.add_argument("--no-temperature", action="store_true")
    a.add_argument("--judge-model", default="openai/gpt-5-mini")
    a.add_argument("--judge-reasoning", default="minimal")
    a.add_argument("--judge-max-tokens", type=int, default=1500)
    a.add_argument("--llm-cache", default=str(Path.home() / ".cogito-mem" / "cache" / "long-history-llm.jsonl"))
    a.add_argument("--workers", type=int, default=8)
    a.add_argument("--split", choices=["tuning", "heldout"])
    a.add_argument("--limit", type=int)
    a.add_argument("--out")
    a.set_defaults(func=cmd_answer)
    g = sub.add_parser("agent", help="the answering model with memory_query and memory_open, per recall design")
    g.add_argument("--data", required=True)
    g.add_argument("--arms", default="tools-only,shipped,pointers", help="tools-only, or names from recall.DESIGNS")
    g.add_argument("--env-file", default=".env")
    g.add_argument("--answer-model", default="anthropic/claude-haiku-5.5")
    g.add_argument("--answer-max-tokens", type=int, default=2000)
    g.add_argument("--judge-model", default="openai/gpt-5-mini")
    g.add_argument("--judge-reasoning", default="minimal")
    g.add_argument("--judge-max-tokens", type=int, default=1500)
    g.add_argument("--llm-cache", default=str(Path.home() / ".cogito-mem" / "cache" / "long-history-llm.jsonl"))
    g.add_argument("--cache", default=str(Path.home() / ".cogito-mem" / "cache" / "embeddings.sqlite3"))
    g.add_argument("--batch", type=int, default=32)
    g.add_argument("--max-steps", type=int, default=6)
    g.add_argument("--workers", type=int, default=4)
    g.add_argument("--split", choices=["tuning", "heldout"])
    g.add_argument("--limit", type=int)
    g.add_argument("--questions-out")
    g.add_argument("--out")
    g.set_defaults(func=cmd_agent)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)
