"""Recall: bring what the memory knows into a Claude Code session without being asked.

Claude Code runs ``cogito-mem recall claude-code`` from two hooks and adds what it
prints to the conversation, so Claude sees earlier work even when it never calls
``memory_query`` (with many MCP servers its tools wait behind tool search):

- ``UserPromptSubmit``: the memory is queried with the prompt. Items that score at
  least ``MIN_SCORE``, share enough of the prompt's words and are not from this
  session come back within ``MAX_TOKENS``, the current project's first, each with
  its date and author.
- ``SessionStart`` (startup, resume): the last exchanges (each prompt with the final
  reply to it) of the most recent earlier session in the same project, read from its
  transcript. It also starts the local
  service if it is down, so the first prompt can be looked up.

Recall never holds up a prompt: on any error, or after ``TIMEOUT`` seconds, it prints
nothing and exits 0, and the reason goes to ``run/recall.log``.
``COGITO_MEM_RECALL=off`` turns it off.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import timeutil
from .capture import jsonl
from .capture.claude_code import items_from_lines, project_folder, project_of, projects_dir
from .terms import query_terms, terms
from .tokenizer import ApproxTokenizer, count, cut

# Query scores are fused ranks (``Namespace.search``): in hybrid search an item that only
# one of the keyword and vector searches found scores at most 0.5, so 0.6 keeps the items
# that both found near the top. A rank does not say how close the match is, though: an
# item sharing a single common word with the prompt still ranks in both searches. So an
# item must also share half of the prompt's content words, at least 2 and at most 4. On a
# copy of a real memory (470 messages) this dropped every item that 9 unrelated prompts
# matched, and kept the closest matches for 9 prompts about the work stored in it. The
# items' ``similarity`` (query-item cosine) separated them no better (requirements §15).
MIN_SCORE = 0.6
MIN_SHARED_WORDS = 2
MAX_SHARED_WORDS = 4
MAX_TOKENS = 300
TIMEOUT = 1.0
MIN_WORDS = 3  # "yes", "go on": nothing to look up
QUERY_CHARS = 2000
LAST_EXCHANGES = 3
MESSAGE_TOKENS = 150
MAX_CONTEXT_CHARS = 9000  # Claude Code moves a longer additionalContext (over 10,000) to a file
TAIL_BYTES = 256 * 1024
MAX_TAIL_BYTES = 8 * 1024 * 1024
TRANSCRIPTS_TRIED = 5

_PATH = re.compile(r"^(?:[/~]|[A-Za-z]:[\\/])")
_tokenizer = ApproxTokenizer()


def enabled() -> bool:
    return os.environ.get("COGITO_MEM_RECALL", "on").strip().lower() not in ("0", "off", "false", "no")


def default_min_score() -> float:
    try:
        return float(os.environ["COGITO_MEM_RECALL_MIN_SCORE"])
    except (KeyError, ValueError):
        return MIN_SCORE


# --------------------------------------------------------------------------- UserPromptSubmit


def prompt_context(
    client: Any, hook: dict, namespace: str = "default", min_score: float = MIN_SCORE, max_tokens: int = MAX_TOKENS
) -> str | None:
    """Earlier items that bear on the prompt, as hook context; None when none qualify."""
    prompt = hook.get("prompt")
    if not isinstance(prompt, str) or prompt.lstrip().startswith("/") or len(prompt.split()) < MIN_WORDS:
        return None
    prompt = prompt[:QUERY_CHARS]
    session = hook.get("session_id")
    project = project_of(hook.get("cwd"))
    words = query_terms(prompt)
    need = min(len(words), MAX_SHARED_WORDS, max(MIN_SHARED_WORDS, math.ceil(len(words) / 2)))
    # Ask for more than fits: this session's own messages match best and are dropped here.
    resp = client.query(prompt, namespace=namespace, top_k=20, max_tokens=3 * max_tokens)
    found = [
        it
        for it in resp["items"]
        if it["score"] >= min_score and it["thread_id"] != session and len(words & set(terms(it["text"]))) >= need
    ]
    found.sort(key=lambda it: _title(it) != project)  # stable: this project's items first, each by score
    lines: list[str] = []
    used = 0
    for it in found:
        text = it["text"].strip()
        if not text:
            continue
        n = count(_tokenizer, text)
        if used + n > max_tokens:
            if lines:
                continue  # a shorter item further down may still fit
            text, n = cut(_tokenizer, text, max_tokens)
            text += " …"
        lines.append(f"- [{_when(it['valid_at'])}, {it['author']}{_where(_title(it), project)}] {_indent(text)}")
        used += n
    if not lines:
        return None
    return "cogito-mem recalled these from earlier sessions; use them only if they help:\n" + "\n".join(lines)


def _title(item: dict) -> str | None:
    return (item.get("source") or {}).get("title")


def _where(title: str | None, project: str | None) -> str:
    if not title:
        return ""
    if title == project:
        return ", this project"
    if _PATH.match(title):
        name = re.split(r"[\\/]", title.rstrip("/\\"))[-1] or title
        return f", project {name}"
    return f", {json.dumps(title[:60], ensure_ascii=False)}"


# --------------------------------------------------------------------------- SessionStart


def session_start_context(hook: dict, projects: Path | None = None, last: int = LAST_EXCHANGES) -> str | None:
    """How the most recent earlier session in this project ended, as hook context; None if there is none."""
    project = project_of(hook.get("cwd"))
    if not project:
        return None
    if projects is None:
        transcript = hook.get("transcript_path")
        projects = Path(transcript).parent.parent if transcript else projects_dir()
    for path in _transcripts(projects, project, hook.get("session_id"))[:TRANSCRIPTS_TRIED]:
        items = _last_exchanges(path, last)
        if any(it.get("title") == project for it in items):  # folder names are lossy: check the cwd
            break
    else:
        return None
    lines = [f"cogito-mem: the last session in this project ({path.stem}, {_when(items[-1].get('valid_at'))}) ended with:"]
    for it in items:
        full = it["text"].strip()
        text, _ = cut(_tokenizer, full, MESSAGE_TOKENS)
        lines.append(f"{it['author']}: {_indent(text)}{' …' if len(text) < len(full) else ''}")
    return "\n".join(lines)


def _transcripts(projects: Path, project: str, session: object) -> list[Path]:
    """The transcripts of the project and of its worktrees, newest first, without this session's."""
    name = project_folder(project)
    found = []
    for folder in [projects / name, *projects.glob(name + "--claude-worktrees-*")]:
        if not folder.is_dir():
            continue
        for path in folder.glob("*.jsonl"):
            if path.stem == session:
                continue
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                pass
    return [path for _, path in sorted(found, reverse=True)]


def _last_exchanges(path: Path, want: int) -> list[dict]:
    """The last ``want`` prompts of a transcript, each with the last reply to it, in order.

    The replies in between are left out: in agentic work they are mostly progress notes,
    and the final one says what came of the prompt. Only as much of the end is read as needed.
    """
    size = path.stat().st_size
    window = TAIL_BYTES
    while True:
        start = max(0, size - window)
        with open(path, "rb") as fh:
            fh.seek(start)
            raw = fh.read(size - start).split(b"\n")
        if start:
            raw = raw[1:]  # the first line is cut
        lines = ((i, line.decode("utf-8", "replace")) for i, line in enumerate(raw))
        items = items_from_lines(jsonl(lines), path.stem)
        if sum(it["author"] == "user" for it in items) >= want or not start or window >= MAX_TAIL_BYTES:
            break
        window *= 4
    exchanges: list[dict] = []
    for it in items:
        if it["author"] == "user" or not exchanges:
            exchanges.append({})
        exchanges[-1]["prompt" if it["author"] == "user" else "reply"] = it
    return [it for ex in exchanges[-want:] for it in (ex.get("prompt"), ex.get("reply")) if it]


# --------------------------------------------------------------------------- the hook


def claude_code_hook(
    read: Callable[[], str],
    make_client: Callable[[], Any],
    namespace: str = "default",
    min_score: float | None = None,
    max_tokens: int = MAX_TOKENS,
    timeout: float = TIMEOUT,
    log: Path | None = None,
) -> str | None:
    """The JSON to print for one ``UserPromptSubmit`` or ``SessionStart`` call, or None. Never raises."""
    if not enabled():
        return None
    score = default_min_score() if min_score is None else min_score
    hook: dict = {}

    def context() -> str | None:
        hook.update(json.loads(read()))
        event = hook.get("hook_event_name")
        if event == "UserPromptSubmit":
            return prompt_context(make_client(), hook, namespace, score, max_tokens)
        if event == "SessionStart":
            return session_start_context(hook)
        return None

    out = None
    try:
        text = within(timeout, context)
        if text:
            out = json.dumps(
                {"hookSpecificOutput": {"hookEventName": hook["hook_event_name"], "additionalContext": text[:MAX_CONTEXT_CHARS]}},
                ensure_ascii=False,
            )
    except Exception as exc:  # recall is a hint: say nothing rather than get in the way
        _log(log, hook.get("hook_event_name"), exc)
    if hook.get("hook_event_name") == "SessionStart":
        try:
            within(timeout, lambda: make_client().start_in_background())
        except Exception as exc:
            _log(log, "SessionStart (starting the service)", exc)
    return out


def within(seconds: float, fn: Callable[[], Any]) -> Any:
    """``fn()`` with a deadline: TimeoutError when it takes longer, and its own errors pass through."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=run, name="cogito-mem-recall", daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise TimeoutError(f"no answer within {seconds:g} s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _log(path: Path | None, event: object, exc: BaseException) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{timeutil.format(timeutil.now_ms())} {event or 'hook'}: {type(exc).__name__}: {exc}\n")
    except OSError:
        pass


def _when(stamp: object) -> str:
    """A timestamp as a local date and time."""
    if not isinstance(stamp, str):
        return "date unknown"
    try:
        return datetime.fromtimestamp(timeutil.parse(stamp) / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError, OSError):
        return "date unknown"


def _indent(text: str) -> str:
    return text.replace("\n", "\n  ")
