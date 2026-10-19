"""What every result records (requirements §5): dataset hash, model, commit, machine, time."""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

from .. import __version__


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
