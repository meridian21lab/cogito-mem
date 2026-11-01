"""What every result records (requirements §5): dataset hash, model, commit, machine, time."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

from .. import __version__
from ..api import MAX_TOP_K, parse_query


def query_past_top_k_limit(mem, body: dict) -> dict:
    """The normal query, except ``top_k`` may pass the API's limit.

    100 LoCoMo turns hold about 2,750 tokens, so at larger budgets the limit, not the budget,
    would decide how much comes back.
    """
    req = parse_query({**body, "top_k": min(body["top_k"], MAX_TOP_K)})
    return mem._query(dataclasses.replace(req, top_k=body["top_k"]))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    here = Path(__file__).resolve().parent
    try:
        out = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        )
        commit = out.stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(here), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        return commit + ("-dirty" if dirty else "") if commit else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def machine() -> dict:
    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpus": os.cpu_count(),
        "python": sys.version.split()[0],
        "gpu_layers": os.environ.get("COGITO_MEM_GPU_LAYERS"),
        "threads": os.environ.get("COGITO_MEM_THREADS"),
    }


def quantization(model_name: str | None) -> str | None:
    if not model_name:
        return None
    m = re.search(r"(?i)\b(I?Q\d+_[A-Z0-9_]+|Q\d+_\d|F16|BF16|F32)\b", model_name.replace("-", " ").replace(".", " "))
    return m.group(1).upper() if m else None


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(model_name: str | None) -> dict:
    return {
        "cogito_mem": __version__,
        "commit": git_commit(),
        "model": model_name,
        "quantization": quantization(model_name),
        "machine": machine(),
        "started_utc": utc_now(),
        "argv": sys.argv,
    }


def parse_count(text: str) -> int:
    """'10M' -> 10_000_000, '500k' -> 500_000."""
    text = text.strip().lower().replace("_", "")
    mult = 1
    if text.endswith("k"):
        mult, text = 1_000, text[:-1]
    elif text.endswith("m"):
        mult, text = 1_000_000, text[:-1]
    elif text.endswith("g") or text.endswith("b"):
        mult, text = 1_000_000_000, text[:-1]
    return int(float(text) * mult)


# --------------------------------------------------------------------------- System-1 ranking (system1.py)


def add_system1_args(p) -> None:
    """The flags that put a local System-1 model behind the search (docs/notes/system1_ranker_20261101.md)."""
    g = p.add_argument_group("System-1 ranking (a local decision model reads the question and each candidate)")
    g.add_argument("--system1", help="the model: a GGUF path or the URL of a running llama-server")
    g.add_argument("--system1-kind", default="rerank", choices=["rerank", "noul", "choice"],
                   help="rerank: /v1/rerank (e.g. Qwen3-Reranker); noul or choice: /v1/systemone (e.g. vLLM-SR d3)")  # fmt: skip
    g.add_argument("--candidates", type=int, default=30,
                   help="how many search candidates the model reads (0: every visible item, a full scan)")  # fmt: skip
    g.add_argument("--rerank-context", default="own", choices=["own", "previous", "dated"],
                   help="what the model reads of a candidate (default: own, its author and text)")  # fmt: skip
    g.add_argument("--rerank-fusion", default="rrf", choices=["replace", "rrf"],
                   help="rrf: fuse the model's ranks with the search's (default); replace: the model's order alone")  # fmt: skip
    g.add_argument("--system1-cache", help="SQLite file of scores already computed (reruns read them back)")
    g.add_argument("--system1-threads", type=int, help="CPU threads of the System-1 llama-server")


def system1_settings(args) -> dict:
    """The System-1 part of a run's settings (empty without --system1)."""
    if not getattr(args, "system1", None):
        return {}
    return {"system1": Path(args.system1).name if "://" not in args.system1 else args.system1,
            "system1_kind": args.system1_kind, "candidates": args.candidates,
            "rerank_context": args.rerank_context, "rerank_fusion": args.rerank_fusion}  # fmt: skip


def make_system1(args):
    """(ranker or None, server or None) for the --system1 flags; the ranker caches its scores."""
    if not getattr(args, "system1", None):
        return None, None
    from ..system1 import CachedRanker, ScoreCache, start_system1

    ranker, server = start_system1(args.system1, args.system1_kind, threads=args.system1_threads)
    return CachedRanker(ranker, ScoreCache(args.system1_cache)), server
