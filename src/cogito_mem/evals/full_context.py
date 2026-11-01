"""Can a model read the whole history at all? Measured, not assumed.

    cogito-mem eval full-context sizes --data longmemeval_m_cleaned.json --out results/full/sizes.json
    cogito-mem eval full-context probe --env-file .env --source longmemeval_m_cleaned.json --out results/full/probe.json
    cogito-mem eval full-context sessions --out results/full/sessions.json

The usual baseline for a memory is the whole conversation pasted into the prompt. That stops
being possible once the history outgrows the model's context window, so three measurements:

- ``sizes``: how many LongMemEval questions have a history larger than a limit (chars / 4).
- ``probe``: send real history text of growing size to real models and record what each one
  does: accepted (with the tokens the provider billed) or rejected (with its error). Sizes go
  from large to small and each model stops at its first acceptance, because rejections are free.
  Nothing is cached, and OpenRouter's ``middle-out`` compression is turned off so nothing is
  silently cut.
- ``sessions``: in real Claude Code transcripts, the largest context a model held and how much
  it had compacted away. Counts only; no text leaves the transcripts, and files are numbered.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .common import record, sha256_file, utc_now
from .locomo_qa import read_env_file
from .longmemeval import load

CHARS_PER_TOKEN = 4
LIMITS = (200_000, 400_000, 1_000_000)
SIZES = (5_000_000, 1_500_000, 1_100_000, 990_000, 900_000, 500_000, 200_000)
MODELS = "anthropic/claude-haiku-5.5,anthropic/claude-sonnet-5.5,openai/gpt-5-mini,openai/gpt-oss-120b,qwen/qwen3-235b-a22b-2507"
PROMPT = "Below is a conversation history. After reading it, reply with the single word OK.\n\n"


def history_chars(q: dict) -> int:
    return sum(len(turn.get("content") or "") for session in q["haystack_sessions"] for turn in session)


def percentile(sorted_values: list, share: float):
    return sorted_values[int(share * (len(sorted_values) - 1))]


def summarize_sizes(tokens: list[int], limits=LIMITS) -> dict:
    ordered = sorted(tokens)
    return {
        "questions": len(ordered),
        "tokens": {"min": ordered[0], "median": percentile(ordered, 0.5), "p95": percentile(ordered, 0.95), "max": ordered[-1]},
        "share_over": {str(n): round(sum(t > n for t in ordered) / len(ordered), 4) for n in limits},
    }


def cmd_sizes(args: argparse.Namespace) -> int:
    path = Path(args.data)
    tokens = [history_chars(q) // CHARS_PER_TOKEN for q in load(path)]
    meta = record(None)
    meta.update({"dataset": str(path), "dataset_sha256": sha256_file(path), "tokens_are": "characters / 4", "finished_utc": utc_now()})
    summary = summarize_sizes(tokens)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"meta": meta, "summary": summary}, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def history_text(questions: list[dict], chars: int) -> str:
    """Real turns, one question's history after another, cut to ``chars`` characters."""
    parts: list[str] = []
    used = 0
    for q in questions:
        for session in q["haystack_sessions"]:
            for turn in session:
                line = f"{turn.get('role') or 'user'}: {turn.get('content') or ''}\n"
                parts.append(line)
                used += len(line)
                if used >= chars:
                    return "".join(parts)[:chars]
    raise ValueError(f"the source holds only {used} characters, {chars} were asked for")


def send(base_url: str, key: str, model: str, text: str, max_tokens: int, timeout: float) -> dict:
    """One request. Returns what happened; an HTTP refusal is a result here, not an error."""
    body = {"model": model, "messages": [{"role": "user", "content": PROMPT + text}], "max_tokens": max_tokens,
            "transforms": [], "usage": {"include": True}}  # fmt: skip
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                          "X-Title": "cogito-mem eval"})  # fmt: skip
    t0 = time.perf_counter()
    out: dict = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res = json.loads(resp.read())
        status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        detail = exc.read().decode("utf-8", "replace")
        try:
            res = json.loads(detail)
        except ValueError:
            res = {"error": {"message": detail}}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        status, res = None, {"error": {"message": f"{type(exc).__name__}: {exc}"}}
    out["seconds"] = round(time.perf_counter() - t0, 1)
    out["status"] = status
    choices = res.get("choices") or []
    if res.get("error") or not choices:
        out["accepted"] = False
        err = res.get("error") or {"message": "no choices in the reply"}
        raw = (err.get("metadata") or {}).get("raw") if isinstance(err.get("metadata"), dict) else None
        out["error"] = str(raw or err.get("message"))[:400]
        out["error_code"] = err.get("code")
        return out
    usage = res.get("usage") or {}
    out.update({"accepted": True, "billed_prompt_tokens": usage.get("prompt_tokens"), "cost_usd": usage.get("cost"),
                "served_by": res.get("provider"), "reply": (choices[0]["message"].get("content") or "")[:40]})  # fmt: skip
    return out


def probe(models: list[str], sizes, text_for, send_one, max_cost: float) -> tuple[list[dict], float]:
    """Each model from the largest size down, until it accepts one. Stops when ``max_cost`` is spent."""
    rows, spent = [], 0.0
    for model in models:
        for size in sorted(sizes, reverse=True):
            if spent >= max_cost:
                rows.append({"model": model, "sent_tokens_approx": size, "skipped": "max cost reached"})
                break
            row = {"model": model, "sent_tokens_approx": size, **send_one(model, text_for(size))}
            spent += float(row.get("cost_usd") or 0.0)
            rows.append(row)
            print(json.dumps(row)[:300], file=sys.stderr)
            if row.get("accepted"):
                break
    return rows, round(spent, 4)


def cmd_probe(args: argparse.Namespace) -> int:
    env = dict(os.environ)
    if args.env_file:
        env = {**read_env_file(Path(args.env_file)), **env}
    key = env.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_AUTH_TOKEN")
    if not key:
        print("no API key: set OPENROUTER_API_KEY, or pass --env-file", file=sys.stderr)
        return 2
    base = args.base_url or env.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api"
    source = Path(args.source)
    questions = load(source)
    sizes = tuple(int(s) for s in args.sizes.split(","))
    full = history_text(questions, max(sizes) * CHARS_PER_TOKEN)
    meta = record(None)
    meta.update({"source": str(source), "source_sha256": sha256_file(source), "base_url": base, "max_cost": args.max_cost,
                 "sizes_are": "characters / 4; billed_prompt_tokens is the provider's own count"})  # fmt: skip
    rows, spent = probe(args.models.split(","), sizes, lambda n: full[: n * CHARS_PER_TOKEN],
                        lambda m, t: send(base, key, m, t, args.max_tokens, args.timeout), args.max_cost)  # fmt: skip
    meta["finished_utc"] = utc_now()
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"meta": meta, "cost_usd": spent, "probes": rows}, indent=2))
    print(json.dumps({"cost_usd": spent, "probes": rows}, indent=2))
    return 0


def session_stats(path: str) -> dict | None:
    """The numbers of one transcript: no text, only token counts from ``usage`` and compaction records."""
    peak = last = dropped = 0
    compactions: dict[str, int] = {}
    for line in open(path, errors="ignore"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("subtype") == "compact_boundary":
            info = d.get("compactMetadata") or {}
            if info.get("preTokens"):
                compactions[str(d.get("uuid"))] = int(info["preTokens"])
            dropped = max(dropped, int(info.get("cumulativeDroppedTokens") or 0))
        elif d.get("type") == "assistant" and not d.get("isSidechain"):
            usage = (d.get("message") or {}).get("usage") or {}
            context = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            if context:
                peak, last = max(peak, context), context
    if not peak:
        return None
    return {"peak_context": peak, "last_context": last, "compactions": compactions, "dropped_reported": dropped}


def summarize_sessions(stats: list[dict]) -> dict:
    """Forks repeat their parent's compactions, so each compaction record counts once, in the largest session holding it."""
    seen: set[str] = set()
    rows = []
    for s in sorted(stats, key=lambda x: -sum(x["compactions"].values())):
        new = {u: t for u, t in s["compactions"].items() if u not in seen}
        seen.update(new)
        rows.append({"peak_context": s["peak_context"], "last_context": s["last_context"], "compactions": len(new),
                     "tokens_compacted_away": sum(new.values()), "dropped_reported": s["dropped_reported"],
                     "history_tokens": sum(new.values()) + s["last_context"]})  # fmt: skip
    return {
        "sessions": len(rows),
        "sessions_compacted": sum(r["compactions"] > 0 for r in rows),
        "compactions": sum(r["compactions"] for r in rows),
        "largest_context_held": max(r["peak_context"] for r in rows),
        "sessions_history_over_1M": sum(r["history_tokens"] > 1_000_000 for r in rows),
        "largest_history": max(r["history_tokens"] for r in rows),
        "largest_dropped_reported": max(r["dropped_reported"] for r in rows),
        "sessions_dropped_over_1M": sum(r["dropped_reported"] > 1_000_000 for r in rows),
        "largest_histories": sorted((r for r in rows if r["compactions"]), key=lambda r: -r["history_tokens"])[:15],
    }


def cmd_sessions(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    stats = [s for s in (session_stats(p) for p in glob.glob(str(root / "*" / "*.jsonl"))) if s]
    meta = record(None)
    meta.update({"history_tokens_is": "tokens held at each compaction plus the context at the end; re-read files count again",
                 "finished_utc": utc_now()})  # fmt: skip
    summary = summarize_sessions(stats)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"meta": meta, "summary": summary}, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cogito-mem eval full-context", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sizes", help="how large the histories of a LongMemEval file are")
    s.add_argument("--data", required=True)
    s.add_argument("--out")
    s.set_defaults(func=cmd_sizes)
    r = sub.add_parser("probe", help="send histories of growing size to real models")
    r.add_argument("--source", required=True, help="a LongMemEval file to take real text from")
    r.add_argument("--models", default=MODELS, help="comma-separated OpenRouter model names")
    r.add_argument("--sizes", default=",".join(str(n) for n in SIZES), help="approximate tokens, comma-separated")
    r.add_argument("--max-cost", type=float, default=10.0, help="stop sending once this many dollars are spent")
    r.add_argument("--max-tokens", type=int, default=200, help="output cap of each request")
    r.add_argument("--timeout", type=float, default=600.0)
    r.add_argument("--env-file")
    r.add_argument("--base-url")
    r.add_argument("--out")
    r.set_defaults(func=cmd_probe)
    t = sub.add_parser("sessions", help="contexts held and compacted away in real Claude Code transcripts")
    t.add_argument("--root", default="~/.claude/projects")
    t.add_argument("--out")
    t.set_defaults(func=cmd_sessions)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)
