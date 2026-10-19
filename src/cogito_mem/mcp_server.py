"""The MCP server (stdio): tools ``memory_append`` and ``memory_query`` (requirements §3.5).

It speaks JSON-RPC 2.0, one message per line, and forwards each tool call as the
same request body the HTTP API takes. By default it forwards to the local service
(started on demand), so the model is loaded once however many chats are open.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from typing import IO, Any, Callable

from . import __version__, timeutil
from .errors import ApiError

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """\
cogito-mem is the user's long-term memory. It keeps what was said in earlier chats \
and sessions, word for word, with the time it was said.

- Search it with memory_query whenever the user refers to earlier work or past \
conversations, or asks whether you remember something ("do you remember...", \
"that idea from last week", "what did we decide about..."). Search before saying \
you don't know.
- Save with memory_append the ideas, decisions, open questions and facts the user \
states, as short notes that make sense on their own.
- Results come back as stored text with valid_at, the time it was said. Quote them \
and say when they were said; never invent what the memory does not hold."""

_RFC3339_HINT = "RFC 3339 time with a time zone, e.g. 2026-10-11T00:00:00Z"


def _tools() -> list[dict]:
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%A %Y-%m-%d")
    return [
        {
            "name": "memory_append",
            "title": "Save to memory",
            "description": (
                "Save a note to the user's long-term memory: an idea, a decision, an open question "
                "or a fact the user stated. Write it so it makes sense on its own later. It is stored "
                "word for word with the current time and cannot be edited."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The note, word for word."},
                    "title": {"type": "string", "description": "Optional short title, e.g. the project or topic."},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
        },
        {
            "name": "memory_query",
            "title": "Search memory",
            "description": (
                "Search the user's long-term memory of earlier chats and sessions. Returns the few stored "
                "messages that best match, each with valid_at (when it was said) and a source pointing to "
                "the original message. Turn time phrases into valid_after (inclusive) and valid_before "
                "(exclusive): for 'a week ago' use a window of a few days around that date, for 'last month' "
                f"that month. Today is {today} (UTC); the response's as_of is the current time."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to look for, in the user's own words."},
                    "valid_after": {"type": "string", "description": f"Only items said at or after this {_RFC3339_HINT}."},
                    "valid_before": {"type": "string", "description": f"Only items said before this {_RFC3339_HINT}."},
                    "max_tokens": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100000,
                        "description": "Reading budget for the returned text, in tokens (default 300).",
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        },
    ]


class McpServer:
    def __init__(
        self,
        handle: Callable[[dict], dict],
        namespace: str = "default",
        thread_id: str | None = None,
        thread_from_env: bool = True,
    ):
        self.handle = handle
        self.namespace = namespace
        # the session, when the client gives one (Claude Code passes its session id to the
        # stdio servers it starts; an HTTP session has no such environment)
        env_thread = (os.environ.get("COGITO_MEM_THREAD_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID")) if thread_from_env else None
        self.thread_id = thread_id or env_thread or None
        self.client_name = "assistant"
        self.protocol_version = PROTOCOL_VERSIONS[0]

    # ------------------------------------------------------------------ JSON-RPC

    def run(self, stdin: IO[bytes] | None = None, stdout: IO[bytes] | None = None) -> None:
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError as exc:
                out: Any = _error(None, -32700, f"parse error: {exc}")
            else:
                if isinstance(msg, list):
                    out = [r for r in (self.dispatch(m) for m in msg) if r is not None] or None
                else:
                    out = self.dispatch(msg)
            if out is not None:
                stdout.write(json.dumps(out, ensure_ascii=False).encode("utf-8") + b"\n")
                stdout.flush()

    def dispatch(self, msg: Any) -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
        method = msg.get("method")
        if method is None:  # a response to a request we never send
            return None
        is_request = "id" in msg
        params = msg.get("params") or {}
        try:
            result = self._call(method, params)
        except _RpcError as exc:
            return _error(msg.get("id"), exc.code, exc.message) if is_request else None
        except Exception as exc:  # pragma: no cover - reported to the client, never hidden
            return _error(msg.get("id"), -32603, f"{type(exc).__name__}: {exc}") if is_request else None
        if not is_request:
            return None
        return {"jsonrpc": "2.0", "id": msg["id"], "result": result}

    def _call(self, method: str, params: dict) -> Any:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": _tools()}
        if method == "tools/call":
            return self._tool_call(params)
        if method.startswith("notifications/"):
            return None
        if method in ("resources/list", "prompts/list"):
            return {method.split("/")[0]: []}
        if method == "resources/templates/list":
            return {"resourceTemplates": []}
        raise _RpcError(-32601, f"method not found: {method}")

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        self.protocol_version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        info = params.get("clientInfo") or {}
        name = info.get("name") if isinstance(info, dict) else None
        if isinstance(name, str) and name.strip():
            self.client_name = name.strip()
        return {
            "protocolVersion": self.protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "cogito-mem", "title": "cogito-mem memory", "version": __version__},
            "instructions": INSTRUCTIONS,
        }

    # ------------------------------------------------------------------ tools

    def _tool_call(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise _RpcError(-32602, "arguments must be an object")
        if name == "memory_append":
            build = self._append_body
        elif name == "memory_query":
            build = self._query_body
        else:
            raise _RpcError(-32602, f"unknown tool: {name}")
        try:
            response = self.handle(build(args))
        except ApiError as err:
            return {"content": [{"type": "text", "text": json.dumps(err.body(), ensure_ascii=False)}], "isError": True}
        return {
            "content": [{"type": "text", "text": json.dumps(response, ensure_ascii=False)}],
            "structuredContent": response,
            "isError": False,
        }

    @staticmethod
    def _check(args: dict, allowed: set[str]) -> None:
        unknown = sorted(set(args) - allowed)
        if unknown:
            raise ApiError("invalid_argument", f"unknown argument(s): {', '.join(unknown)}")

    def _append_body(self, args: dict) -> dict:
        self._check(args, {"text", "title"})
        item = {
            "author": self.client_name,
            "valid_at": timeutil.format(timeutil.now_ms()),
            "text": args.get("text"),
            "title": args.get("title"),
        }
        if self.thread_id:
            item["thread_id"] = self.thread_id
        return {"op": "append", "namespace": self.namespace, "items": [item]}

    def _query_body(self, args: dict) -> dict:
        self._check(args, {"text", "valid_after", "valid_before", "max_tokens"})
        body: dict = {"op": "query", "namespace": self.namespace, "text": args.get("text")}
        flt = {k: args[k] for k in ("valid_after", "valid_before") if args.get(k) is not None}
        if flt:
            body["filter"] = flt
        if args.get("max_tokens") is not None:
            body["max_tokens"] = args["max_tokens"]
        return body


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}
