#!/usr/bin/env python3
"""Token-budget coverage on LongMemEval_M: one token counter, one text rule, every system.

    PYTHONPATH=<frozen src> .venv/bin/python budget_score.py cogi --data-dir D --rows cogi.jsonl --out cogi.json
    ... budget_score.py shipped --data-dir D --rows x.jsonl --name N --out x.json          real output, cut at the budget
    ... budget_score.py documents --data-dir D --rank rows --name N --out x.json            session documents in ranked order
    ... budget_score.py generous --data-dir D --rank rows --name N --k 10 --unit message --out y.json
    ... budget_score.py compare --cogi cogi.json --cogi-src src --out comparison.json x.json y.json ...

Shared token counter: the EmbeddingGemma 2 tokenizer through llama-server's /tokenize, the one Cogi's own budgets use.
Rules are in docs/notes/longmemeval_m_rivals_20261101.md, written before any rival was scored.

Evidence: the `has_answer` turns of the question's answer sessions, skipping empty turns, as Cogi's loader does.
A message is **present** when passages from its own session share at least 100 consecutive characters with it (lowercased,
whitespace collapsed), or hold all of it if it is shorter. Validated on Cogi's replies against its message ids. It is **whole** when
95% of its 100-character windows are there. A question is covered when all its evidence messages are present, or whole.

Nothing here can see evidence labels when choosing text: `generous` reads only the question and the rival's ranking.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from cogito_mem.tokenizer import count, cut

BUDGETS = (1000, 2500, 5000)
WINDOW = 100
WHOLE = 0.95
WORD = re.compile(r"[a-z0-9]+")
K1, B = 1.2, 0.75
PIECE = 256
DEJA_HEAD = re.compile(r"^\d+\. \[[A-Za-z0-9_.-]+\] .* · (\S+)$")
DEJA_LABEL = re.compile(r"^- (?:[A-Z][^:]{0,60}: )?")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def presence(evidence: list[tuple[str, str]], reply: dict[str, list[str]]) -> tuple[bool, bool, int]:
    """(all present, all whole, how many present). Evidence is (session, normalised text); reply maps session -> passages."""
    cache: dict[str, tuple[str, set[str]]] = {}
    present, whole = 0, 0
    for sid, m in evidence:
        if sid not in cache:
            hay = norm(" ".join(reply.get(sid, [])))
            cache[sid] = (hay, {hay[i : i + WINDOW] for i in range(max(0, len(hay) - WINDOW + 1))})
        hay, have = cache[sid]
        if len(m) < WINDOW:
            hit = m in hay
            present += hit
            whole += hit
            continue
        mine = [m[i : i + WINDOW] for i in range(len(m) - WINDOW + 1)]
        found = sum(1 for s in mine if s in have)
        present += found > 0
        whole += found / len(mine) >= WHOLE
    n = len(evidence)
    return n > 0 and present == n, n > 0 and whole == n, present


class Dataset:
    def __init__(self, data_dir: str):
        self.dir = Path(data_dir)
        self.manifest = json.loads((self.dir / "manifest.json").read_text())
        self.rows = {r["question_id"]: r for r in self.manifest["rows"]}

    def question(self, qid: str) -> dict:
        return json.loads((self.dir / "q" / self.rows[qid]["file"]).read_text())[0]

    @staticmethod
    def evidence(q: dict) -> list[tuple[str, str]]:
        """(session, normalised text) of each distinct evidence message."""
        present = {str(s) for s in q["haystack_session_ids"]}
        want = {str(s) for s in q.get("answer_session_ids") or []} & present
        out: dict[tuple[str, str], None] = {}
        for sid, session in zip(q["haystack_session_ids"], q["haystack_sessions"]):
            if str(sid) not in want:
                continue
            for turn in session:
                text = turn.get("content") or ""
                if turn.get("has_answer") and text.strip():
                    out[(str(sid), norm(text))] = None
        return list(out)


def to_reply(items: list[tuple[str, str]]) -> dict[str, list[str]]:
    reply: dict[str, list[str]] = defaultdict(list)
    for sid, text in items:
        reply[sid].append(text)
    return reply


def pack_cut(passages: list[tuple[str, str]], budget: int, tok) -> tuple[list[tuple[str, str]], int]:
    """In ranked order; the passage that passes the limit is cut there and filling stops."""
    parts, used = [], 0
    for sid, text in passages:
        n = count(tok, text)
        if used + n >= budget:
            piece, took = cut(tok, text, budget - used)
            if piece:
                parts.append((sid, piece))
            used += took
            break
        parts.append((sid, text))
        used += n
    return parts, used


def pack_like_cogi(passages: list[tuple[str, str]], budget: int, tok) -> tuple[list[tuple[str, str]], int]:
    """Cogi's own packing: in order, the first is cut if over, later ones that don't fit are skipped."""
    parts, used = [], 0
    for sid, text in passages:
        if used >= budget:
            break
        n = count(tok, text)
        if not parts and n > budget:
            text, n = cut(tok, text, budget)
        elif used + n > budget:
            continue
        parts.append((sid, text))
        used += n
    return parts, used


def deja_blocks(page: str) -> list[tuple[str, str]]:
    """One (session, snippet text) per hit on a recall page. Frame, notices and heading lines aren't message text."""
    out: list[tuple[str, str]] = []
    sid, lines = None, []
    for raw in page.split("\n"):
        line = raw.strip()
        m = DEJA_HEAD.match(line)
        if m:
            if sid and lines:
                out.append((sid, "\n".join(lines)))
            sid, lines = m.group(1), []
        elif sid and line.startswith("</deja-recall"):
            break
        elif sid and line.startswith("- "):
            lines.append(DEJA_LABEL.sub("", line).replace("…", " "))
    if sid and lines:
        out.append((sid, "\n".join(lines)))
    return out


def row_common(qid: str, ds: Dataset) -> dict:
    return {"question_id": qid, "question_type": ds.rows[qid]["question_type"], "abstention": "_abs" in qid}


def tokenizer():
    from cogito_mem.evals.longmemeval import make_embedder
    from cogito_mem.runtime import LlamaServerTokenizer

    embedder, rt = make_embedder("auto", None)
    inner = LlamaServerTokenizer(rt.base, embedder.name)
    memo: dict[str, list[int]] = {}

    class Memo:  # the same message is asked for at each budget
        name = inner.name

        @staticmethod
        def offsets(text: str) -> list[int]:
            if text not in memo:
                if len(memo) > 300_000:
                    memo.clear()
                memo[text] = inner.offsets(text)
            return memo[text]

    return Memo, rt, embedder.name


def read_jsonl(path: str) -> tuple[dict, dict[str, dict]]:
    lines = Path(path).read_text().split("\n")
    head = json.loads(lines[0])
    rows: dict[str, dict] = {}
    for line in lines[1:]:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        rows[r["question_id"]] = r
    return head, rows


def summarize(rows: list[dict]) -> dict:
    """Coverage per budget on the labelled questions and the answerable, with query time and tokens used."""
    out: dict = {}
    sets = {"labelled": [r for r in rows if r["evidence"]], "answerable": [r for r in rows if r["evidence"] and not r["abstention"]]}
    for name, rs in sets.items():
        cell: dict = {"n": len(rs)}
        for b in map(str, BUDGETS):
            if not rs:
                continue
            xs = [r["budgets"][b] for r in rs]
            q = sorted(x.get("query_ms", 0) for x in xs)
            t = sorted(x["tokens"] for x in xs)
            cell[b] = {
                "coverage": round(sum(x["all"] for x in xs) / len(xs), 4),
                "whole": round(sum(x["whole"] for x in xs) / len(xs), 4),
                "any": round(sum(x["present"] > 0 for x in xs) / len(xs), 4),
                "tokens_median": t[len(t) // 2],
                "passages_median": sorted(x["passages"] for x in xs)[len(xs) // 2],
                "query_ms_median": round(q[len(q) // 2], 2),
                "query_ms_p95": round(q[int(0.95 * (len(q) - 1))], 2),
            }
        out[name] = cell
    return out


def cmd_cogi(args) -> int:
    ds = Dataset(args.data_dir)
    tok, rt, model = tokenizer()
    head, rows_in = read_jsonl(args.rows)
    rows, id_agree, total, yes_no, no_yes = [], 0, 0, 0, 0
    try:
        for qid in ds.rows:
            r = rows_in.get(qid)
            if r is None:
                continue
            ev = Dataset.evidence(ds.question(qid))
            row = {**row_common(qid, ds), "evidence": len(ev), "evidence_ids": r["evidence_id_count"], "budgets": {}}
            want = set(r["evidence_ids"])
            for b in map(str, BUDGETS):
                reply = r["replies"][b]
                got = {it["id"] for it in reply["items"]}
                by_id = bool(want) and want <= got
                ordered = sorted(reply["items"], key=lambda it: (it["id"], it["start"]))  # a whole message reads through
                a, w, p = presence(ev, to_reply([(it["thread"], it["text"]) for it in ordered]))
                row["budgets"][b] = {"all": a, "whole": w, "present": p, "by_id": by_id, "any_by_id": bool(want & got), "tokens": reply["tokens"],
                                     "shared_tokens": sum(count(tok, it["text"]) for it in reply["items"]), "passages": len(reply["items"]),
                                     "query_ms": reply["query_ms"]}  # fmt: skip
                if want:
                    total += 1
                    id_agree += by_id == a
                    yes_no += a and not by_id
                    no_yes += by_id and not a
            rows.append(row)
    finally:
        rt.stop()
    summary = summarize(rows)
    labelled = [r for r in rows if r["evidence"]]
    answerable = [r for r in labelled if not r["abstention"]]
    by_id = {name: {b: round(sum(r["budgets"][b]["by_id"] for r in rs) / max(1, len(rs)), 4) for b in map(str, BUDGETS)}
             for name, rs in (("labelled", labelled), ("answerable", answerable))}  # fmt: skip
    meta = {**head.get("settings", {}), "name": "cogi", "tokenizer": model, "rule_text_vs_id_agreement": f"{id_agree}/{total}",
            "text_yes_id_no": yes_no, "text_no_id_yes": no_yes}  # fmt: skip
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"meta": meta, "summary": summary, "coverage_by_id": by_id, "per_question": rows}))
    print(json.dumps({"coverage_by_id": by_id, "n": {k: summary[k]["n"] for k in summary}, "agreement": meta["rule_text_vs_id_agreement"], "yes_no": yes_no, "no_yes": no_yes}))
    return 0


def passages_of(items: list) -> list[tuple[str, str]]:
    return [(str(it["s"]), it["t"]) for it in items]


def cmd_shipped(args) -> int:
    """Rows hold `replies` per budget, `ranked` passages to fill from, or deja's raw `pages`."""
    ds = Dataset(args.data_dir)
    tok, rt, model = tokenizer()
    head, rows_in = read_jsonl(args.rows)
    rows = []
    try:
        for qid in ds.rows:
            r = rows_in.get(qid)
            if r is None:
                continue
            ev = Dataset.evidence(ds.question(qid))
            row = {**row_common(qid, ds), "evidence": len(ev), "budgets": {}}
            for b in BUDGETS:
                if "replies" in r:
                    passages, ms = passages_of(r["replies"][str(b)]["passages"]), r["replies"][str(b)]["query_ms"]
                elif "pages" in r:
                    # Pages are read in order until the budget is filled; time is what those pages took.
                    passages, ms, held = [], 0.0, 0
                    for page, page_ms in zip(r["pages"], r["page_ms"]):
                        if held >= b:
                            break
                        blocks = deja_blocks(page)
                        passages += blocks
                        held += sum(count(tok, t) for _, t in blocks)
                        ms += page_ms
                else:
                    passages, ms = passages_of(r["ranked"]), r.get("query_ms", 0)
                parts, used = pack_cut(passages, b, tok)
                a, w, p = presence(ev, to_reply(parts))
                row["budgets"][str(b)] = {"all": a, "whole": w, "present": p, "tokens": used, "passages": len(parts), "query_ms": ms}
            rows.append(row)
    finally:
        rt.stop()
    write_result(args, head, model, rows)
    return 0


def read_ranking(path: str) -> tuple[dict[str, list[str]], dict[str, float]]:
    """Ranked session ids per question and its query time, from a rows file (up to 100) or a result file (up to 20)."""
    if path.endswith(".jsonl"):
        rows = read_jsonl(path)[1]
        return {q: r["ranked_sessions"] for q, r in rows.items()}, {q: r.get("query_ms", 0) for q, r in rows.items()}
    rows = json.loads(Path(path).read_text())["per_question"]
    return {r["question_id"]: r["ranked_sessions"] for r in rows}, {r["question_id"]: r.get("query_ms", 0) for r in rows}


def cmd_documents(args) -> int:
    """MemPalace's benchmark documents: a session's user turns joined, whole, in ranked order, the last cut at the limit."""
    ds = Dataset(args.data_dir)
    tok, rt, model = tokenizer()
    ranking, times = read_ranking(args.rank)
    rows = []
    try:
        for qid in ds.rows:
            ranked = ranking.get(qid)
            if ranked is None:
                continue
            q = ds.question(qid)
            ev = Dataset.evidence(q)
            docs = {}
            for sid, session in zip(q["haystack_session_ids"], q["haystack_sessions"]):
                docs[str(sid)] = "\n".join(t["content"] for t in session if t["role"] == "user")
            passages = [(str(s), docs[str(s)]) for s in dict.fromkeys(ranked) if docs.get(str(s))]
            row = {**row_common(qid, ds), "evidence": len(ev), "budgets": {}}
            for b in BUDGETS:
                parts, used = pack_cut(passages, b, tok)
                a, w, p = presence(ev, to_reply(parts))
                row["budgets"][str(b)] = {"all": a, "whole": w, "present": p, "tokens": used, "passages": len(parts), "query_ms": times.get(qid, 0)}
            rows.append(row)
    finally:
        rt.stop()
    write_result(args, {"settings": {"returns": "session documents, user turns only, in the benchmark's rank order", "rank_file": args.rank}}, model, rows)
    return 0


def bm25_order(query: str, docs: list[str]) -> list[int]:
    """Plain BM25 over these documents only, lowercase alphanumeric words, no stemming. Zero-score documents are dropped."""
    terms = set(WORD.findall(query.lower()))
    bags = [Counter(WORD.findall(d.lower())) for d in docs]
    lens = [sum(b.values()) for b in bags]
    n = len(docs)
    avg = sum(lens) / max(1, n)
    df = Counter(t for b in bags for t in b if t in terms)
    scores = []
    for i, b in enumerate(bags):
        s = 0.0
        for t in terms:
            f = b.get(t, 0)
            if f:
                idf = math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1)
                s += idf * f * (K1 + 1) / (f + K1 * (1 - B + B * lens[i] / max(avg, 1e-9)))
        scores.append(s)
    return [i for i in sorted(range(n), key=lambda i: (-scores[i], i)) if scores[i] > 0]


def cmd_generous(args) -> int:
    ds = Dataset(args.data_dir)
    tok, rt, model = tokenizer()
    ranking, _ = read_ranking(args.rank)
    rows = []
    try:
        for qid in ds.rows:
            ranked = ranking.get(qid)
            if ranked is None:
                continue
            q = ds.question(qid)
            ev = Dataset.evidence(q)
            turns = {str(s): t for s, t in zip(q["haystack_session_ids"], q["haystack_sessions"])}
            top = list(dict.fromkeys(ranked))[: args.k]
            docs: list[tuple[str, str]] = []
            for sid in top:
                for turn in turns.get(str(sid), []):
                    text = turn.get("content") or ""
                    if not text.strip():
                        continue
                    if args.unit == "message":
                        docs.append((str(sid), text))
                    else:
                        ends = tok.offsets(text)
                        start = 0
                        for i in range(PIECE - 1, len(ends), PIECE):
                            docs.append((str(sid), text[start : ends[i]]))
                            start = ends[i]
                        if start < len(text):
                            docs.append((str(sid), text[start:]))
            t0 = time.perf_counter()
            order = bm25_order(q["question"], [d[1] for d in docs])
            pick_ms = (time.perf_counter() - t0) * 1000
            passages = [docs[i] for i in order]
            row = {**row_common(qid, ds), "evidence": len(ev), "budgets": {}}
            for b in BUDGETS:
                parts, used = pack_like_cogi(passages, b, tok)
                a, w, p = presence(ev, to_reply(parts))
                row["budgets"][str(b)] = {"all": a, "whole": w, "present": p, "tokens": used, "passages": len(parts), "query_ms": pick_ms}
            rows.append(row)
    finally:
        rt.stop()
    head = {"settings": {"construction": "ours, not a product feature", "rank_file": args.rank, "k": args.k, "unit": args.unit,
                         "picker": f"BM25 k1={K1} b={B} over the {args.unit}s of the top {args.k} sessions; packed as Cogi packs"}}  # fmt: skip
    write_result(args, head, model, rows)
    return 0


def write_result(args, head: dict, model: str, rows: list[dict]) -> None:
    summary = summarize(rows)
    meta = {**head.get("settings", {}), "name": args.name, "tokenizer": model, "scored_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"meta": meta, "summary": summary, "per_question": rows}))
    print(args.name, "n", summary["labelled"]["n"], {b: summary["labelled"][b]["coverage"] for b in map(str, BUDGETS)},
          "whole", {b: summary["labelled"][b]["whole"] for b in map(str, BUDGETS)},
          "tok", {b: summary["labelled"][b]["tokens_median"] for b in map(str, BUDGETS)})  # fmt: skip


def load_bootstrap(src: Path):
    source = (src / "cogito_mem/evals/longmemeval.py").read_text()
    keep = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "paired_bootstrap"]
    ns: dict = {"random": random}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "longmemeval.py", "exec"), ns)  # noqa: S102
    return ns["paired_bootstrap"]


def cmd_compare(args) -> int:
    bootstrap = load_bootstrap(Path(args.cogi_src))
    cogi_file = json.loads(Path(args.cogi).read_text())
    cogi = {r["question_id"]: r for r in cogi_file["per_question"]}
    report: dict = {"cogi": cogi_file["summary"], "cogi_by_id": cogi_file.get("coverage_by_id"), "cogi_meta": cogi_file["meta"], "rivals": {},
                    "bootstrap": "paired_bootstrap, 10000 resamples of questions, seed 0"}  # fmt: skip
    for path in args.rivals:
        data = json.loads(Path(path).read_text())
        rival = {r["question_id"]: r for r in data["per_question"]}
        entry: dict = {"meta": data["meta"], "summary": data["summary"]}
        for label, keep in (("labelled", lambda r: True), ("answerable", lambda r: not r["abstention"])):
            ids = [q for q in cogi if q in rival and cogi[q]["evidence"] and keep(cogi[q])]
            bad = [q for q in ids if cogi[q]["evidence"] != rival[q]["evidence"]]
            if bad:
                raise SystemExit(f"{path}: evidence counts differ on {bad[:3]}")
            cell: dict = {"n": len(ids)}
            for b in map(str, BUDGETS):
                for metric, key in (("coverage", "all"), ("whole", "whole")):
                    x = [float(rival[q]["budgets"][b][key]) for q in ids]
                    y = [float(cogi[q]["budgets"][b][key]) for q in ids]
                    mean, lo, hi = bootstrap(x, y, 10_000, 0)
                    cell[f"{metric}@{b}"] = {
                        "rival": round(100 * sum(x) / len(x), 2), "cogi": round(100 * sum(y) / len(y), 2),
                        "cogi_minus_rival": round(100 * mean, 2), "ci95": [round(100 * lo, 2), round(100 * hi, 2)],
                        "cogi_only": sum(1 for a, c in zip(x, y) if c > a), "rival_only": sum(1 for a, c in zip(x, y) if a > c),
                    }  # fmt: skip
            entry[label] = cell
        report["rivals"][Path(path).stem] = entry
    Path(args.out).write_text(json.dumps(report, indent=1))
    for name, e in report["rivals"].items():
        c = e["labelled"]
        print(f"{name:40} n={c['n']} " + "  ".join(f"{c[f'coverage@{b}']['rival']:5.1f} ({c[f'coverage@{b}']['cogi_minus_rival']:+5.1f} [{c[f'coverage@{b}']['ci95'][0]:+.1f},{c[f'coverage@{b}']['ci95'][1]:+.1f}])" for b in map(str, BUDGETS)))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, func in (("cogi", cmd_cogi), ("shipped", cmd_shipped)):
        a = sub.add_parser(name)
        a.add_argument("--data-dir", required=True)
        a.add_argument("--rows", required=True)
        a.add_argument("--name", default=name)
        a.add_argument("--out", required=True)
        a.set_defaults(func=func)
    a = sub.add_parser("documents")
    a.add_argument("--data-dir", required=True)
    a.add_argument("--rank", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--out", required=True)
    a.set_defaults(func=cmd_documents)
    a = sub.add_parser("generous")
    a.add_argument("--data-dir", required=True)
    a.add_argument("--rank", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--k", type=int, default=10)
    a.add_argument("--unit", default="message", choices=["message", "piece"])
    a.add_argument("--out", required=True)
    a.set_defaults(func=cmd_generous)
    a = sub.add_parser("compare")
    a.add_argument("--cogi", required=True)
    a.add_argument("--cogi-src", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("rivals", nargs="+")
    a.set_defaults(func=cmd_compare)
    args = p.parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
