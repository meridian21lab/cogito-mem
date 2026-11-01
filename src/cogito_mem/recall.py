"""Recall: bring what the memory knows into a Claude Code session without being asked.

Claude Code runs ``cogito-mem recall claude-code`` from two hooks and adds what it
prints to the conversation, so Claude sees earlier work even when it never calls
``memory_query`` (with many MCP servers its tools wait behind tool search):

- ``UserPromptSubmit``: the memory is queried with the prompt. ``COGITO_MEM_RECALL_DESIGN``
  picks what comes back. ``shipped``: items that score at least ``MIN_SCORE``, share enough
  of the prompt's words and are not from this session, within ``MAX_TOKENS``, the current
  project's first, each with its date and author. Messages come before the notes of what a
  turn did (author ``actions``), which only fill the room left. ``pointers``: up to
  ``POINTERS`` one-line pointers Claude can open with ``memory_open``, so more of the earlier
  work fits, from other sessions, from this session's own text that compaction removed, and,
  on their own lines, from sessions still running in this project.
- ``SessionStart`` (startup, resume): the last exchanges (each prompt with the final
  reply to it) of the most recent earlier session in the same project, read from its
  transcript. It also starts the local
  service if it is down, so the first prompt can be looked up.
- ``SessionStart`` (compact), with the ``pointers`` design: what of this session the
  summary may have lost, as pointers.
- ``PostToolUse`` (edits), with ``COGITO_MEM_RECALL_TOOLS=on``: earlier messages naming the
  file, once per file per session, because tool calls far outnumber prompts.

Every injection, and what was withheld under ``COGITO_MEM_RECALL_HOLDOUT``, goes to the
ledger (``run/ledger.jsonl``), which ``cogito-mem report`` reads.

Recall never holds up a prompt: on any error, or after ``TIMEOUT`` seconds, it prints
nothing and exits 0, and the reason goes to ``run/recall.log``.
``COGITO_MEM_RECALL=off`` turns it off.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import ledger, timeutil
from .capture import jsonl
from .capture.claude_code import ACTIONS, items_from_lines, project_folder, project_of, projects_dir
from .terms import identifiers, query_terms, terms
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
SIDE_AUTHORS = (ACTIONS, "tool")  # what sessions did, as against what was said

# Pointers. A rank near the top of either list is worth a line, since a line costs little; the word gate
# stays, at one word fewer, because a rank alone does not say the match is close (see above).
POINTERS = 8
POINTER_MIN_SCORE = 0.45
POINTER_POOL = 40
SNIPPET_TOKENS = 28
SIBLINGS = 3
SIBLING_MS = 6 * 3600 * 1000
OWN_AFTER_COMPACT = 6
COMPACT_SCAN_BYTES = 64 * 1024 * 1024
TOOL_POINTERS = 3
EDIT_TOOLS = ("Edit", "MultiEdit", "Write", "NotebookEdit")
_SENTENCE = re.compile(r"(?<=[.?!:;])\s+|\n+")

_PATH = re.compile(r"^(?:[/~]|[A-Za-z]:[\\/])")
_tokenizer = ApproxTokenizer()


def enabled() -> bool:
    return os.environ.get("COGITO_MEM_RECALL", "on").strip().lower() not in ("0", "off", "false", "no")


def design_name() -> str:
    name = os.environ.get("COGITO_MEM_RECALL_DESIGN", DEFAULT_DESIGN).strip().lower()
    return name if name in DESIGNS else DEFAULT_DESIGN


def withheld(session: object) -> bool:
    """Whether this session is in the share kept without recall, for comparing outcomes (by a hash of its id)."""
    try:
        share = float(os.environ.get("COGITO_MEM_RECALL_HOLDOUT", "0"))
    except ValueError:
        return False
    if share <= 0 or not isinstance(session, str):
        return False
    return int(hashlib.sha256(session.encode()).hexdigest(), 16) % 100 < share


def default_min_score() -> float:
    try:
        return float(os.environ["COGITO_MEM_RECALL_MIN_SCORE"])
    except (KeyError, ValueError):
        return MIN_SCORE


# --------------------------------------------------------------------------- UserPromptSubmit


@dataclass
class Shot:
    """What one hook call would add: the text, and the items it came from."""

    text: str | None = None
    items: list[dict] = field(default_factory=list)


def _usable_prompt(hook: dict) -> str | None:
    prompt = hook.get("prompt")
    if not isinstance(prompt, str) or prompt.lstrip().startswith("/") or len(prompt.split()) < MIN_WORDS:
        return None
    return prompt[:QUERY_CHARS]


def prompt_context(
    client: Any, hook: dict, namespace: str = "default", min_score: float = MIN_SCORE, max_tokens: int = MAX_TOKENS
) -> str | None:
    """Earlier items that bear on the prompt, as hook context; None when none qualify."""
    return shipped(client, hook, namespace, min_score, max_tokens).text


def shipped(
    client: Any, hook: dict, namespace: str = "default", min_score: float = MIN_SCORE, max_tokens: int = MAX_TOKENS
) -> Shot:
    """The items themselves, within ``max_tokens``."""
    prompt = _usable_prompt(hook)
    if prompt is None:
        return Shot()
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
    # Stable: this project's items first, and in each, messages before ``actions`` items (what a
    # turn did), which only take the room the messages leave; each by score.
    found.sort(key=lambda it: (_title(it) != project, it["author"] in SIDE_AUTHORS))
    lines: list[str] = []
    kept: list[dict] = []
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
        kept.append(it)
        used += n
    if not lines:
        return Shot()
    return Shot("cogito-mem recalled these from earlier sessions; use them only if they help:\n" + "\n".join(lines), kept)


def pointers(client: Any, hook: dict, namespace: str = "default", min_score: float = POINTER_MIN_SCORE) -> Shot:
    """One line per earlier message, for Claude to open if it matters.

    A long message costs what its line costs, so eight places cover more of the history than 300 tokens of whole
    messages do. This session's own messages count once compaction has taken them out of Claude's context.
    """
    prompt = _usable_prompt(hook)
    if prompt is None:
        return Shot()
    session = hook.get("session_id")
    project = project_of(hook.get("cwd"))
    compacted = compacted_at(hook.get("transcript_path"))
    words = query_terms(prompt)
    need = min(len(words), MAX_SHARED_WORDS, max(1, math.ceil(len(words) / 2) - 1))
    kwargs: dict = {"filter": dict(hook["filter"])} if hook.get("filter") else {}
    resp = client.query(prompt, namespace=namespace, top_k=POINTER_POOL, max_tokens=POINTER_POOL * 400, **kwargs)
    found: dict[str, dict] = {}
    for it in resp["items"]:
        if it["score"] < min_score or len(words & set(terms(it["text"]))) < need:
            continue
        if not it["text"].strip() or it["author"] in SIDE_AUTHORS:
            continue
        if it["thread_id"] == session and not _before(it, compacted):
            continue
        found.setdefault(it["source"]["id"], it)
    siblings = _siblings(client, hook, prompt, namespace, project, words, need) if project else []
    sibling_ids = {it["source"]["id"] for it in siblings}
    main = [it for key, it in found.items() if key not in sibling_ids][: POINTERS - len(siblings)]
    if not main and not siblings:
        return Shot()
    lines = ["cogito-mem points at these earlier messages. Each line is a short excerpt: if one bears on this, read it "
             "with memory_open(id) before relying on it, or before redoing the work."]  # fmt: skip
    lines += [_pointer(it, project, words) for it in main]
    if siblings:
        lines.append("Said in the last hours in other sessions of this project, which may still be running:")
        lines += [_pointer(it, project, words) for it in siblings]
    return Shot("\n".join(lines), main + siblings)


def _siblings(client: Any, hook: dict, prompt: str, namespace: str, project: str, words: set[str], need: int) -> list[dict]:
    now = hook.get("now_ms") or timeutil.now_ms()
    flt = {**(hook.get("filter") or {}), "valid_after": timeutil.format(now - SIBLING_MS)}
    resp = client.query(prompt, namespace=namespace, top_k=POINTER_POOL, max_tokens=POINTER_POOL * 400, filter=flt)
    found: dict[str, dict] = {}
    for it in resp["items"]:
        if it["thread_id"] != hook.get("session_id") and _title(it) == project and it["author"] not in SIDE_AUTHORS \
                and len(words & set(terms(it["text"]))) >= need:  # fmt: skip
            found.setdefault(it["source"]["id"], it)
    return list(found.values())[:SIBLINGS]


def _pointer(item: dict, project: str | None, words: set[str]) -> str:
    return (f"- {item['source']['id'][-12:]} [{_when(item['valid_at'])}, {item['author']}{_where(_title(item), project)}] "
            f"{snippet(item['text'], words)}")  # fmt: skip


def snippet(text: str, words: set[str], max_tokens: int = SNIPPET_TOKENS) -> str:
    """The sentence sharing most words with the query, as far as it fits on one line."""
    parts = [p.strip() for p in _SENTENCE.split(text) if p.strip()]
    if not parts:
        return ""
    best = max(parts, key=lambda p: len(words & set(terms(p))))
    short, _ = cut(_tokenizer, best, max_tokens)
    short = " ".join(short.split())
    return short if short == " ".join(text.split()) else short + " …"


def _before(item: dict, moment: int | None) -> bool:
    if moment is None or not isinstance(item.get("valid_at"), str):
        return False
    try:
        return timeutil.parse(item["valid_at"]) < moment
    except ValueError:
        return False


def compacted_at(transcript: object) -> int | None:
    """When this session last compacted, from the end of its transcript; None if it has not."""
    if not isinstance(transcript, str):
        return None
    try:
        with open(transcript, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            start = max(0, size - COMPACT_SCAN_BYTES)
            fh.seek(start)
            data = fh.read(size - start)
    except OSError:
        return None
    at = data.rfind(b'"subtype":"compact_boundary"')
    if at < 0:
        return None
    begin = data.rfind(b"\n", 0, at) + 1
    end = data.find(b"\n", at)
    try:
        return timeutil.parse(json.loads(data[begin : end if end >= 0 else len(data)])["timestamp"])
    except (ValueError, KeyError, TypeError):
        return None


def _last_prompt(transcript: object) -> str | None:
    if not isinstance(transcript, str):
        return None
    try:
        items = _last_exchanges(Path(transcript), 1)
    except OSError:
        return None
    return next((it["text"] for it in items if it["author"] == "user"), None)


def compact_context(client: Any, hook: dict, namespace: str = "default") -> Shot:
    """After compaction: what of this session the summary may have lost, in the words it was said."""
    session = hook.get("session_id")
    if not isinstance(session, str):
        return Shot()
    project = project_of(hook.get("cwd"))
    head = ("cogito-mem holds this whole session word for word, including what the summary left out: "
            "memory_query with this_session, memory_open(id) for the exact text.")  # fmt: skip
    prompt = _last_prompt(hook.get("transcript_path"))
    if not prompt or not prompt.strip():
        return Shot(head)
    flt: dict = {"thread_id": session}
    moment = compacted_at(hook.get("transcript_path"))
    if moment is not None:
        flt["valid_before"] = timeutil.format(moment)
    resp = client.query(prompt[:QUERY_CHARS], namespace=namespace, top_k=POINTER_POOL, max_tokens=POINTER_POOL * 400, filter=flt)
    found: dict[str, dict] = {}
    for it in resp["items"]:
        if it["author"] not in SIDE_AUTHORS and it["text"].strip():
            found.setdefault(it["source"]["id"], it)
    kept = list(found.values())[:OWN_AFTER_COMPACT]
    words = query_terms(prompt)
    return Shot("\n".join([head, *(_pointer(it, project, words) for it in kept)]), kept)


def tool_context(client: Any, hook: dict, namespace: str = "default", seen: set[str] | None = None) -> Shot:
    """Earlier messages naming the file about to change, from other sessions, each file once a session."""
    tool_input = hook.get("tool_input")
    path = tool_input.get("file_path") or tool_input.get("notebook_path") if isinstance(tool_input, dict) else None
    if hook.get("tool_name") not in EDIT_TOOLS or not isinstance(path, str) or not path.strip():
        return Shot()
    name = path.rsplit("/", 1)[-1].lower()
    if seen is not None:
        if path in seen:
            return Shot()
        seen.add(path)
    project = project_of(hook.get("cwd"))
    if len(name) < 4:
        return Shot()
    resp = client.query(f"what was decided about {name}", namespace=namespace, top_k=POINTER_POOL, max_tokens=POINTER_POOL * 400)
    found: dict[str, dict] = {}
    for it in resp["items"]:
        if it["thread_id"] != hook.get("session_id") and it["author"] not in SIDE_AUTHORS and name in it["text"].lower() \
                and (project is None or _title(it) == project):  # fmt: skip
            found.setdefault(it["source"]["id"], it)
    kept = list(found.values())[:TOOL_POINTERS]
    if not kept:
        return Shot()
    words = identifiers(name) | query_terms(name)
    lines = [f"cogito-mem: earlier messages name {name}; memory_open(id) reads one, if it bears on this edit."]
    return Shot("\n".join(lines + [_pointer(it, project, words) for it in kept]), kept)


def _seen_path(log: Path | None, session: object) -> Path | None:
    if log is None or not isinstance(session, str):
        return None
    return log.parent / "recall-seen" / re.sub(r"[^\w-]", "_", session)


def _read_seen(path: Path | None) -> set[str]:
    try:
        return set(path.read_text(encoding="utf-8").splitlines()) if path else set()
    except OSError:
        return set()


def _write_seen(path: Path | None, keys: set[str]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(sorted(keys)), encoding="utf-8")
    except OSError:
        pass


DEFAULT_DESIGN = "shipped"
DESIGNS: dict[str, Callable[..., Shot]] = {"shipped": shipped, "pointers": pointers}


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

    design = design_name()

    def context() -> Shot:
        hook.update(json.loads(read()))
        event = hook.get("hook_event_name")
        if event == "UserPromptSubmit":
            if design == "pointers":
                seen_at = _seen_path(log, hook.get("session_id"))
                seen = _read_seen(seen_at)
                shot = pointers(make_client(), hook, namespace)
                fresh = [it for it in shot.items if it["source"]["id"] not in seen]
                if not fresh:
                    return Shot()
                if len(fresh) < len(shot.items):  # no line twice in a session: it is already in the context
                    shot = _without(shot, seen)
                _write_seen(seen_at, seen | {it["source"]["id"] for it in fresh})
                return shot
            return shipped(make_client(), hook, namespace, score, max_tokens)
        if event == "SessionStart":
            if hook.get("source") == "compact":
                if design == "pointers":
                    seen_at = _seen_path(log, hook.get("session_id"))
                    _write_seen(seen_at, set())  # compaction took what had been shown out of the context
                    return compact_context(make_client(), hook, namespace)
                return Shot()
            return Shot(session_start_context(hook))
        if event == "PostToolUse" and os.environ.get("COGITO_MEM_RECALL_TOOLS", "off").strip().lower() in ("1", "on", "true", "yes"):
            seen_at = _seen_path(log, hook.get("session_id"))
            seen = _read_seen(seen_at)
            shot = tool_context(make_client(), hook, namespace, seen)
            _write_seen(seen_at, seen)
            return shot
        return Shot()

    out = None
    started = time.perf_counter()
    try:
        shot = within(timeout, context)
        hold = withheld(hook.get("session_id"))
        if shot.text and not hold:
            out = json.dumps(
                {"hookSpecificOutput": {"hookEventName": hook["hook_event_name"], "additionalContext": shot.text[:MAX_CONTEXT_CHARS]}},
                ensure_ascii=False,
            )
        ledger.record(
            log.parent if log is not None else None,
            {
                "event": hook.get("hook_event_name"),
                "session": hook.get("session_id"),
                "design": design,
                "fired": bool(shot.text),
                "withheld": hold and bool(shot.text),
                "items": [it["source"]["id"] for it in shot.items],
                "tokens": count(_tokenizer, shot.text) if shot.text else 0,
                "prompt_tokens": count(_tokenizer, hook["prompt"]) if isinstance(hook.get("prompt"), str) else 0,
                "ms": round((time.perf_counter() - started) * 1000),
            },
        )
    except Exception as exc:  # recall is a hint: say nothing rather than get in the way
        _log(log, hook.get("hook_event_name"), exc)
    if hook.get("hook_event_name") == "SessionStart":
        try:
            within(timeout, lambda: make_client().start_in_background())
        except Exception as exc:
            _log(log, "SessionStart (starting the service)", exc)
    return out


def _without(shot: Shot, seen: set[str]) -> Shot:
    """The shot with the lines of what was already shown taken out."""
    kept = [it for it in shot.items if it["source"]["id"] not in seen]
    tails = {it["source"]["id"][-12:] for it in shot.items if it["source"]["id"] in seen}
    lines = [ln for ln in (shot.text or "").split("\n") if not (ln.startswith("- ") and ln[2:14] in tails)]
    return Shot("\n".join(lines), kept)


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
