"""Claude Code: read the session transcript (JSONL) after each turn.

The ``Stop`` and ``SessionEnd`` hooks run ``cogito-mem capture claude-code``, which
reads the hook's JSON from stdin and hands the work to a background process, so
the chat never waits for the memory.

Kept: the user's typed messages and the assistant's text replies, without what is
marked ``<private>…</private>``, and what the session did: one ``actions`` item for
each run of tool calls between two prompts, with the commands it ran (and which
failed or did not run) and the files it read, edited or wrote, such as
"Ran `pytest -q` (failed), `pytest -q`. Edited src/x.py. Read README.md."
(``COGITO_MEM_CAPTURE_ACTIONS=off`` leaves these out).

Also kept: what each sub-agent handed back, as one ``subagent`` item, whether its
turns are in the session's transcript (``isSidechain``) or, as now, in files of their
own at ``<session>/subagents/agent-<id>.jsonl`` (``COGITO_MEM_CAPTURE_SUBAGENTS=off``
leaves these out); and, by rule, the telling lines of what tools returned, as
``tool`` items with the command in front: the end of a failed command's output, lines
that carry an error or a metric, and the last lines of a long output
(``COGITO_MEM_CAPTURE_TOOL_OUTPUT=off`` leaves these out).

Left out: other tool output, file contents, thinking, the sub-agents' other turns,
slash-command output, injected system reminders and the summary Claude Code writes
when it compacts a session.

``client_ref`` is the transcript line's ``uuid`` (for an ``actions`` item, that of its
first tool call, so reading a turn again, whole or from its middle, adds no second
copy); ``thread_id`` is the session id; ``title`` is the project, the line's ``cwd``
(a Claude Code worktree, ``<repo>/.claude/worktrees/<name>``, counts as its
repository), so recall can prefer the current project.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Iterable

from . import Cursor, Sink, enabled, jsonl, read_new_lines, redact, send, without_private

ACTIONS = "actions"  # the author of what a turn did (store.SIDE_AUTHOR)
SUBAGENT = "subagent"  # the author of what a sub-agent handed back
TOOL = "tool"  # the author of the lines kept of a tool's result
ACTION_CHARS = 800  # about one piece (``split.PIECE_TOKENS``), so a busy turn cannot fill a reply
COMMAND_CHARS = 80
TOOL_TURN_CHARS = 3 * ACTION_CHARS  # of a turn's tool output, so a long run of commands cannot swamp its messages
TOOL_LINE_CHARS = 240
FAILED_LINES = 10  # of a failed command's output: the end says why
LONG_OUTPUT_LINES = 10  # of a longer successful output, the last lines are kept too
LAST_LINES = 2
HANDBACK = "SubagentHandback"  # the tool some sub-agents hand their report back with, instead of a last reply

_SKIP_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "Caveat: The messages below were generated",
    "[Request interrupted by user",
    "<user-prompt-submit-hook>",
    "This session is being continued from a previous conversation",  # a compaction summary
    "<task-notification>",  # a background task finishing, reported to Claude, not typed
)
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_WORKTREE = re.compile(r"[\\/]\.claude[\\/]worktrees[\\/][^\\/]+.*$", re.S)
_VERBS = {"Read": "Read", "NotebookRead": "Read", "Edit": "Edited", "MultiEdit": "Edited", "NotebookEdit": "Edited",
          "Write": "Wrote"}  # fmt: skip
_NOT_RUN = ("<tool_use_error>", "The user doesn't want to", "[Request interrupted")
_EXIT_CODE = re.compile(r"Exit code (\d+)")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# A line worth keeping of a tool's output: an error or a test count, or a metric (a number after a name, a percentage,
# a duration). ``key=value`` needs a number: with any value this also takes environment dumps, URLs and tokens.
_SIGNAL = re.compile(
    r"(?i:\berrors?\b|\bfailed\b|\bfailures?\b|\bpassed\b|\bfatal\b)|\b\w*(?:Error|Exception)\b|Traceback"
    r"|(?<![\w./-])[A-Za-z_][\w.-]*\"?\s*[=:]\s*[-+]?\d[\d.,]*(?:[eE][-+]?\d+)?\s?(?:%|[a-zA-Zµ]{1,3})?(?=[\s,;)\]}]|$)"
    r"|\b\d+(?:\.\d+)?\s?%"
    r"|\b\d+(?:\.\d+)?\s?(?:ms|s|secs?|seconds?|mins?|minutes?|h|hours?)\b"
)
# A command that only shows files is a Read by another name: its lines are the files' contents, not results.
_SHOWS_FILES = re.compile(
    r"(?:cd\s+\S+\s*(?:&&|;)\s*)?(?:cat|head|sed|awk|nl|less|more|bat|ls|find|tree|grep|egrep|rg|ag|fd|wc|stat|file"
    r"|echo|printf|git(?:\s+-C\s+\S+)?\s+(?:diff|show|log|blame|status|grep|ls-files|branch))\b"
)


def projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "projects"


def project_of(cwd: object) -> str | None:
    """The project a working directory belongs to: the directory, or a worktree's repository."""
    if not isinstance(cwd, str) or not cwd.strip():
        return None
    cwd = cwd.rstrip("/\\") or cwd
    return _WORKTREE.sub("", cwd) or cwd


def project_folder(project: str) -> str:
    """The folder name Claude Code gives a project under ``~/.claude/projects``."""
    return re.sub(r"[^A-Za-z0-9]", "-", project)


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n\n".join(p for p in parts if p)
    return ""


def items_from_lines(
    lines: Iterable[tuple[int, dict]],
    session_id: str | None = None,
    actions: bool = False,
    tool_output: bool = False,
    subagents: bool = False,
) -> list[dict]:
    """The messages as items, in order; with ``actions``, also one item per turn for its tool calls;
    with ``tool_output``, the kept lines of the tools' results; with ``subagents``, what the sub-agents in
    these lines handed back."""
    items = []
    turns: list[tuple[dict, dict]] = []  # (actions item, its tool calls by id)
    calls: dict | None = None  # the tool calls of the turn under way
    used: dict = {}  # every tool call, by id, for the command in front of its output
    outputs: list[list[tuple[bool, dict]]] = [[]]  # the ``tool`` items by turn, each with whether its command failed
    for _, rec in lines:
        kind = rec.get("type")
        if subagents and kind == "assistant" and rec.get("isSidechain"):
            report = _report(rec, session_id)
            if report:
                items.append(report)
        if kind not in ("user", "assistant") or any(rec.get(k) for k in ("isSidechain", "isMeta", "isCompactSummary")):
            continue
        message = rec.get("message")
        if not isinstance(message, dict):
            continue
        text = without_private(_REMINDER.sub("", _text_of(message.get("content")))).strip()
        if text and not text.startswith(_SKIP_PREFIXES) and rec.get("uuid"):
            author = "user" if kind == "user" else "assistant"
            items.append(_item(rec, author, redact(text), f"claude-code:{rec['uuid']}", session_id))
        if not actions and not tool_output:
            continue
        content = message.get("content")
        blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
        if kind == "user" and not any(b.get("type") == "tool_result" for b in blocks):
            calls = None  # a prompt: the turn's actions end here
            outputs.append([])
        for block in blocks:
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                used[block.get("id")] = block
                if not actions:
                    continue
                if calls is None:
                    if not rec.get("uuid"):
                        continue
                    calls = {}
                    turns.append((_item(rec, ACTIONS, "", f"claude-code:{rec['uuid']}:actions", session_id), calls))
                    items.append(turns[-1][0])
                call = {"name": block.get("name"), "input": block["input"], "cwd": rec.get("cwd")}
                calls[block.get("id") or len(calls)] = call
            elif block.get("type") == "tool_result":
                outcome = _outcome(block)
                if calls is not None and block.get("tool_use_id") in calls:
                    calls[block["tool_use_id"]]["outcome"] = outcome
                output = _tool_item(rec, block, outcome, used.get(block.get("tool_use_id")), session_id) if tool_output else None
                if output:
                    items.append(output)
                    outputs[-1].append((outcome == "failed", output))
    for item, turn in turns:
        item["text"] = _summary(list(turn.values()))
    for turn_output in outputs:
        room = TOOL_TURN_CHARS
        # What failed goes first, as it says what went wrong, then the newest, as they say how the turn came out.
        for _, item in sorted(reversed(turn_output), key=lambda kept: not kept[0]):
            room -= len(item["text"])
            if room < 0:
                item["text"] = ""
    return [it for it in items if it["text"]]


def _item(rec: dict, author: str, text: str, client_ref: str, session_id: str | None) -> dict:
    item = {
        "author": author,
        "thread_id": rec.get("sessionId") or session_id or "default",
        "text": text,
        "client_ref": client_ref,
    }
    project = project_of(rec.get("cwd"))
    if project:
        item["title"] = project
    if isinstance(rec.get("timestamp"), str):
        item["valid_at"] = rec["timestamp"]
    return item


def _report(rec: dict, session_id: str | None) -> dict | None:
    """What a sub-agent handed back on this line, if it did: its last reply, or the call it hands back with.

    A reply that ends the sub-agent's turn says so (``stop_reason``), which holds however little of its
    transcript has been read, and whichever replies it wrote on the way there are left out.
    """
    message = rec.get("message")
    if not isinstance(message, dict) or not rec.get("uuid"):
        return None
    content = message.get("content")
    text = _text_of(content) if message.get("stop_reason") == "end_turn" else ""
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == HANDBACK:
            handed = block.get("input")
            text = handed.get("message") if isinstance(handed, dict) else None
    text = without_private(_REMINDER.sub("", text)).strip() if isinstance(text, str) else ""
    return _item(rec, SUBAGENT, redact(text), f"claude-code:{rec['uuid']}", session_id) if text else None


def _tool_item(rec: dict, result: dict, outcome: str | None, call: dict | None, session_id: str | None) -> dict | None:
    """The lines kept of one tool's result, by rule, after its command; None when none are.

    Nothing of a Read: that is a file's contents. Of the other tools, what a failure said; only tools that run a
    command also have their errors, metrics and last lines kept when they succeed.
    """
    if call is None or not rec.get("uuid") or _VERBS.get(call.get("name")) == "Read":
        return None
    args = call["input"]
    command = args.get("command") if isinstance(args.get("command"), str) and args["command"].strip() else None
    # Redacted whole and before it is cut: a key spans lines, and no part of a secret may be left.
    text = redact(without_private(_ANSI.sub("", _REMINDER.sub("", _text_of(result.get("content"))))))
    lines = [line.rstrip().rsplit("\r", 1)[-1] for line in text.split("\n")]
    lines = [line for line in lines if line.strip()]
    if lines and _EXIT_CODE.fullmatch(lines[0]):  # ``(failed)`` in front says that
        lines = lines[1:]
    has_results = command is not None and not _SHOWS_FILES.match(_command(command, _cwd(rec)))
    picks = [i for i, line in enumerate(lines) if _SIGNAL.search(line)] if has_results else []
    if outcome:
        picks += range(max(0, len(lines) - FAILED_LINES), len(lines))
    elif has_results and len(lines) > LONG_OUTPUT_LINES:
        picks += range(len(lines) - LAST_LINES, len(lines))
    if not picks:
        return None
    if command is not None:
        what = f"`{_command(command, _cwd(rec))}`"
    else:
        path = args.get("file_path") or args.get("notebook_path")
        what = f"{call.get('name')} {_relative(path, _cwd(rec))}" if isinstance(path, str) else str(call.get("name"))
    head = what + (f" ({outcome})" if outcome else "") + ":"
    kept: list[str] = []
    room = ACTION_CHARS - len(head) - 2
    chosen = list(dict.fromkeys(_cut_line(lines[i]) for i in sorted(set(picks))))
    for line in reversed(chosen):  # from the end: the last lines say how it came out
        room -= len(line) + 1
        if room < 0:
            break
        kept.append(line)
    if len(kept) < len(chosen):
        kept.append("…")
    client_ref = f"claude-code:{rec['uuid']}:tool:{result.get('tool_use_id')}"
    return _item(rec, TOOL, "\n".join([head, *reversed(kept)]), client_ref, session_id)


def _cwd(rec: dict) -> str:
    return rec["cwd"] if isinstance(rec.get("cwd"), str) else ""


def _cut_line(line: str) -> str:
    return line if len(line) <= TOOL_LINE_CHARS else line[:TOOL_LINE_CHARS].rstrip() + " …"


def _outcome(result: dict) -> str | None:
    """``failed``, ``not run`` (refused or interrupted), or None for a call that went through."""
    text = _text_of(result.get("content")).lstrip()
    if text.startswith(_NOT_RUN):
        return "not run"
    code = _EXIT_CODE.match(text)
    if result.get("is_error") or (code and code.group(1) != "0"):
        return "failed"
    return None


def _summary(calls: list[dict]) -> str:
    """One sentence per kind of action: the commands in order, then the files by what was done to them."""
    commands: list[str] = []
    files: dict[str, list[str]] = {}
    for call in calls:
        args, outcome = call["input"], call.get("outcome")
        cwd = call["cwd"] if isinstance(call["cwd"], str) else ""
        if call["name"] == "Bash" and isinstance(args.get("command"), str) and args["command"].strip():
            entry = f"`{_command(args['command'], cwd)}`" + (f" ({outcome})" if outcome else "")
            if entry not in commands:
                commands.append(entry)
            continue
        path = args.get("file_path") or args.get("notebook_path")
        if not isinstance(path, str) or not path.strip() or outcome:  # a failed edit changed nothing
            continue
        paths = files.setdefault(_VERBS.get(call["name"]) or f"Used {call['name']} on", [])
        if _relative(path, cwd) not in paths:
            paths.append(_relative(path, cwd))
    changed = {p for verb, paths in files.items() if verb != "Read" for p in paths}
    if "Read" in files:  # files are read before they are edited: that says nothing more
        files["Read"] = [p for p in files["Read"] if p not in changed]
    kinds = [("Ran", commands), *sorted(files.items(), key=lambda kv: kv[0] == "Read")]
    parts = [(verb, entries) for verb, entries in kinds if entries]
    # Each kind gets an equal share of the room, and what a short one leaves goes to the others.
    texts = [""] * len(parts)
    room = ACTION_CHARS
    by_length = sorted(range(len(parts)), key=lambda i: sum(len(e) + 2 for e in parts[i][1]))
    for left, i in zip(range(len(parts), 0, -1), by_length):
        texts[i] = _listing(*parts[i], room // left)
        room -= len(texts[i]) + 1
    text = redact(" ".join(texts))
    return text if len(text) <= ACTION_CHARS else text[: ACTION_CHARS - 2] + " …"


def _listing(verb: str, entries: list[str], room: int) -> str:
    """``Verb a, b, c.`` with as many entries as fit in ``room`` characters, and how many more there were."""
    text = verb
    for n, entry in enumerate(entries):
        if n and len(text) + len(entry) + (3 if n == len(entries) - 1 else 18) > room:
            return f"{text}, and {len(entries) - n} more."
        text += (", " if n else " ") + entry
    return text + "."


def _command(command: str, cwd: str) -> str:
    """The command's first line, cut to ``COMMAND_CHARS``, with paths under ``cwd`` relative to it."""
    command = redact(command.strip())  # before it is cut, so no part of a secret is left
    base = re.escape(cwd.rstrip("/\\"))
    if base:
        command = re.sub(rf"^cd +([\"']?){base}[/\\]?\1 *(?:&&|;) *", "", command)
        command = re.sub(rf"(?<![^\s\"'=:(]){base}[/\\]", "", command)
    first, *rest = command.splitlines() or [""]
    if rest or len(first) > COMMAND_CHARS:
        first = first[:COMMAND_CHARS].rstrip() + " …"
    return first


def _relative(path: str, cwd: str) -> str:
    base = cwd.rstrip("/\\")
    if base and path.startswith(base) and path[len(base) : len(base) + 1] in ("/", "\\"):
        return path[len(base) + 1 :]
    return path


def capture_transcript(
    sink: Sink,
    transcript: Path,
    state_dir: Path,
    session_id: str | None = None,
    namespace: str = "default",
    import_: bool = False,
) -> dict:
    """Append the new messages of one transcript. Returns counts of added and duplicate items."""
    session = session_id or transcript.stem
    subagents = enabled("COGITO_MEM_CAPTURE_SUBAGENTS")

    def read(lines: Iterable[tuple[int, dict]]) -> list[dict]:
        return items_from_lines(lines, session, actions=enabled("COGITO_MEM_CAPTURE_ACTIONS"),
                                tool_output=enabled("COGITO_MEM_CAPTURE_TOOL_OUTPUT"), subagents=subagents)  # fmt: skip

    def read_reports(lines: Iterable[tuple[int, dict]]) -> list[dict]:
        found = (_report(rec, session) for _, rec in lines if rec.get("type") == "assistant")
        return [it for it in found if it]

    cursors = state_dir / "claude-code"
    counts = _capture_file(sink, transcript, cursors / f"{_safe(session)}.json", read, namespace, import_)
    for path in subagent_files(transcript) if subagents else []:
        cursor = cursors / f"{_safe(session)}.{_safe(path.stem)}.json"
        more = _capture_file(sink, path, cursor, read_reports, namespace, import_)
        counts = {key: counts[key] + more[key] for key in counts}
    return counts


def _capture_file(
    sink: Sink, path: Path, cursor_file: Path, read: Callable[[Iterable[tuple[int, dict]]], list[dict]], namespace: str, import_: bool
) -> dict:
    cursor = Cursor(cursor_file)
    lines, offset, line = read_new_lines(path, cursor.offset, cursor.line)
    items = read(jsonl(lines))
    if import_:
        items = [it for it in items if "valid_at" in it]
    counts = send(sink, items, namespace, import_) if items else {"added": 0, "duplicate": 0}
    cursor.save(offset, line)
    return counts


def subagent_files(transcript: Path) -> list[Path]:
    """The transcripts of a session's sub-agents, but not of the one that writes its compaction summary."""
    found = (transcript.parent / transcript.stem / "subagents").rglob("*.jsonl")
    return sorted(path for path in found if not path.name.startswith("agent-acompact"))


def capture_all(sink: Sink, state_dir: Path, namespace: str = "default", root: Path | None = None) -> dict:
    """Backfill every transcript under ~/.claude/projects (as history, with ``import``)."""
    total = {"added": 0, "duplicate": 0, "files": 0}
    base = root or projects_dir()
    if not base.is_dir():
        return total
    for path in sorted(base.glob("*/*.jsonl")):
        counts = capture_transcript(sink, path, state_dir, path.stem, namespace, import_=True)
        total["added"] += counts["added"]
        total["duplicate"] += counts["duplicate"]
        total["files"] += 1
    return total


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:128]
