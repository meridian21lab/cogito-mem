#!/usr/bin/env python3
"""`deja recall` on LongMemEval_M: the page its CLI and MCP tool print, with later pages by --offset.

    python budget_deja.py --deja <built deja> --data-dir <split> --work <dir> --out rows.jsonl

Writes each haystack as Claude-format transcripts, as its scripts/longmemeval does, points DEJA_CLAUDE_ROOT and DEJA_INDEX_DIR
at them and runs the real CLI: `deja recall -- "<question>"`, five hits to a page within 4 KB, then --offset 5, 10... until enough
text is held for the largest budget or it says there are no more. It has no token-budget option, so the pages are
the output and the scorer cuts them at each budget. The frame and each hit's heading line are dropped, as Cogi's metadata isn't
counted either. DEJA_RECALL_GLOBAL=1 because no session here belongs to a project in the current directory.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HEAD = re.compile(r"^\d+\. \[[A-Za-z0-9_.-]+\]")
ENOUGH_CHARS = 5000 * 6  # well over the largest budget, measured later by the shared counter
MAX_PAGES = 30


def when(s: str) -> datetime:
    try:
        return datetime.strptime(s.split(" (")[0] + " " + s.split(") ")[1], "%Y/%m/%d %H:%M").replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return datetime(2023, 1, 1, tzinfo=timezone.utc)


def write_transcripts(q: dict, root: Path) -> None:
    proj = root / "-work-lme"
    proj.mkdir(parents=True)
    for sid, date, turns in zip(q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"]):
        ts = when(date)
        with open(proj / f"{sid}.jsonl", "w", encoding="utf-8") as f:
            for ti, turn in enumerate(turns):
                content = turn["content"]
                if turn["role"] == "assistant":
                    content = [{"type": "text", "text": turn["content"]}]
                f.write(json.dumps({"type": turn["role"], "sessionId": sid, "timestamp": (ts + timedelta(minutes=ti)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "message": {"role": turn["role"], "content": content}}) + "\n")  # fmt: skip


def body(page: str) -> str:
    out = []
    for line in page.split("\n"):
        s = line.strip()
        if s.startswith(("<deja-recall", "</deja-recall")) or HEAD.match(s) or not s:
            continue
        out.append(s)
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deja", required=True)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--sample", default="all")
    p.add_argument("--out", required=True)
    p.add_argument("--header", default="{}")
    args = p.parse_args()
    data_dir, work, out = Path(args.data_dir), Path(args.work), Path(args.out)
    manifest = json.loads((data_dir / "manifest.json").read_text())
    selected = None if args.sample == "all" else set(manifest["samples"][args.sample])
    done: set[str] = set()
    if out.exists() and out.stat().st_size:
        lines = out.read_text().split("\n")
        if lines[0] != args.header:
            raise SystemExit(f"{out} holds other settings: {lines[0][:200]}")
        for line in lines[1:]:
            try:
                done.add(json.loads(line)["question_id"])
            except (ValueError, KeyError):
                pass
    else:
        out.write_text(args.header + "\n")
    start = time.perf_counter()
    ran = 0
    with open(out, "a", encoding="utf-8") as log:
        for row in manifest["rows"]:
            qid = row["question_id"]
            if qid in done or (selected is not None and qid not in selected):
                continue
            q = json.loads((data_dir / "q" / row["file"]).read_text(encoding="utf-8"))[0]
            root = work / "current"
            if root.exists():
                shutil.rmtree(root)
            (root / "index").mkdir(parents=True)
            write_transcripts(q, root / "claude")
            env = {**os.environ, "DEJA_CLAUDE_ROOT": str(root / "claude"), "DEJA_INDEX_DIR": str(root / "index"), "DEJA_RECALL_GLOBAL": "1"}
            pages, page_ms, offset, held, stop = [], [], 0, 0, ""
            while held < ENOUGH_CHARS and len(pages) < MAX_PAGES:
                cmd = [args.deja, "recall", "--limit", "5", "--offset", str(offset), "--", q["question"]]
                t0 = time.perf_counter()
                proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=900)
                ms = (time.perf_counter() - t0) * 1000
                if proc.returncode != 0:
                    raise RuntimeError(f"{qid}: deja recall exited {proc.returncode}: {proc.stderr[:300]}")
                if "No more " in proc.stdout or (offset == 0 and not proc.stdout.strip()):
                    stop = proc.stdout.strip()[:120]
                    break
                text = body(proc.stdout)
                pages.append(text)
                page_ms.append(ms)
                held += len(text)
                offset += 5
            log.write(json.dumps({"question_id": qid, "ranked": pages, "page_ms": page_ms, "stop": stop}) + "\n")
            log.flush()
            ran += 1
            if ran % 10 == 0:
                print(f"{ran} questions, {time.perf_counter() - start:.0f} s", flush=True)
    print(f"done: {ran} questions run, {time.perf_counter() - start:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
