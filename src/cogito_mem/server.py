"""The local service: ``POST /v1/memory`` and MCP over HTTP at ``/mcp`` (requirements §3).

One warm process holds the memory and the embedding model; the MCP bridge, the
capture hooks and the command line all talk to it. It answers only requests whose
``Host`` is local (or listed in ``COGITO_MEM_ALLOWED_HOSTS``), whose ``Origin``, if
any, is local, and whose body is JSON, so a web page can neither read nor write it.
It exits after an idle period; clients start it again on demand.

``/mcp`` is the MCP Streamable HTTP transport (JSON responses, no server-sent
events), so a client can connect by URL, e.g. to the Docker image:
``claude mcp add --transport http cogito-mem http://127.0.0.1:7327/mcp``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .api import NAMESPACE_RE
from .errors import ApiError
from .mcp_server import McpServer
from .memory import Memory

log = logging.getLogger("cogito_mem")

DEFAULT_PORT = 7327
MAX_BODY = 64 * 1024 * 1024
MAX_MCP_SESSIONS = 1000
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def default_port() -> int:
    return int(os.environ.get("COGITO_MEM_PORT", DEFAULT_PORT))


def allowed_hosts() -> set[str]:
    extra = {h.strip().lower() for h in os.environ.get("COGITO_MEM_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return _LOCAL_HOSTS | extra


def _host_name(host: str) -> str:
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return (host.rsplit(":", 1)[0] if host.count(":") == 1 else host).lower()


class _Handler(BaseHTTPRequestHandler):
    server_version = f"cogito-mem/{__version__}"
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True  # headers and body go out at once, not 40 ms apart
    server: "MemoryServer"

    def log_message(self, fmt: str, *args) -> None:
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: object | None, headers: dict[str, str] | None = None) -> None:
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, err: ApiError) -> None:
        self._send(err.http_status, err.body())

    def _trusted(self) -> bool:
        """Host is local (DNS rebinding) and Origin, when a browser sends one, is local too."""
        hosts = self.server.allowed_hosts
        host = self.headers.get("Host")
        if host is not None and _host_name(host) not in hosts:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != "null":
            name = urlsplit(origin).hostname or ""
            if (f"[{name}]" if ":" in name else name).lower() not in hosts:
                return False
        return origin != "null"

    def _read_body(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            self.close_connection = True
            self._error(ApiError("invalid_argument", f"Content-Length must be 0 to {MAX_BODY} bytes"))
            return None
        return self.rfile.read(length)

    def do_GET(self) -> None:  # noqa: N802
        self.server.touch()
        if not self._trusted():
            return self._error(ApiError("permission_denied", "only local requests are served"))
        path = urlsplit(self.path).path
        if path == "/v1/status":
            return self._send(200, {"status": "ok", "pid": os.getpid(), **self.server.memory.status()})
        if path == "/mcp":  # no server-initiated stream is offered
            return self._send(405, None, {"Allow": "POST, DELETE"})
        self._error(ApiError("not_found", f"no such path: {self.path}"))

    def do_DELETE(self) -> None:  # noqa: N802
        self.server.touch()
        if not self._trusted():
            return self._error(ApiError("permission_denied", "only local requests are served"))
        if urlsplit(self.path).path != "/mcp":
            return self._error(ApiError("not_found", f"no such path: {self.path}"))
        self.server.end_mcp_session(self.headers.get("Mcp-Session-Id"))
        self._send(200, None)

    def do_POST(self) -> None:  # noqa: N802
        self.server.touch()
        raw = self._read_body()
        if raw is None:
            return
        if not self._trusted():
            return self._error(ApiError("permission_denied", "only local requests are served"))
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._error(ApiError("invalid_argument", "Content-Type must be application/json"))
        url = urlsplit(self.path)
        if url.path == "/mcp":
            return self._mcp(raw, parse_qs(url.query))
        if url.path != "/v1/memory":
            return self._error(ApiError("not_found", f"no such path: {self.path}; use POST /v1/memory"))
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            return self._error(ApiError("invalid_argument", f"the body is not valid JSON: {exc}"))
        t0 = time.perf_counter()
        try:
            result = self.server.memory.handle(body)
        except ApiError as err:
            return self._error(err)
        except Exception as exc:  # pragma: no cover - reported, never hidden
            log.exception("request failed")
            return self._error(ApiError("internal", f"{type(exc).__name__}: {exc}"))
        if "took_ms" in result:
            result["took_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        self._send(200, result)

    def _mcp(self, raw: bytes, query: dict[str, list[str]]) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {exc}"}})
        messages = msg if isinstance(msg, list) else [msg]
        initializing = any(isinstance(m, dict) and m.get("method") == "initialize" for m in messages)
        headers: dict[str, str] = {}
        session_id = self.headers.get("Mcp-Session-Id")
        if initializing:
            namespace = (query.get("namespace") or ["default"])[0]
            if not NAMESPACE_RE.match(namespace):
                return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32602, "message": "bad namespace"}})
            session_id, mcp = self.server.new_mcp_session(namespace)
            headers["Mcp-Session-Id"] = session_id
        else:
            mcp = self.server.mcp_session(session_id)
            if mcp is None:
                return self._send(404, {"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32001, "message": "unknown session; initialize again"}})  # fmt: skip
        replies = [r for r in (mcp.dispatch(m) for m in messages) if r is not None]
        if not replies:
            return self._send(202, None, headers)
        self._send(200, replies if isinstance(msg, list) else replies[0], headers)

    def do_OPTIONS(self) -> None:  # noqa: N802 - no CORS: browsers may not call this service
        self._error(ApiError("permission_denied", "cross-origin requests are not served"))


class MemoryServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, memory: Memory, host: str = "127.0.0.1", port: int = DEFAULT_PORT, idle_timeout: float = 0):
        super().__init__((host, port), _Handler)
        self.memory = memory
        self.idle_timeout = idle_timeout
        self.allowed_hosts = allowed_hosts()
        self._last = time.monotonic()
        self.run_file: Path | None = None
        self._sessions: OrderedDict[str, McpServer] = OrderedDict()
        self._sessions_lock = threading.Lock()

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        return f"http://{host}:{port}"

    def touch(self) -> None:
        self._last = time.monotonic()

    # ------------------------------------------------------------------ MCP sessions

    def new_mcp_session(self, namespace: str) -> tuple[str, McpServer]:
        session_id = uuid.uuid4().hex
        mcp = McpServer(self.memory.handle, namespace=namespace, thread_from_env=False)
        with self._sessions_lock:
            self._sessions[session_id] = mcp
            while len(self._sessions) > MAX_MCP_SESSIONS:
                self._sessions.popitem(last=False)
        return session_id, mcp

    def mcp_session(self, session_id: str | None) -> McpServer | None:
        if not session_id:
            return None
        with self._sessions_lock:
            mcp = self._sessions.get(session_id)
            if mcp is not None:
                self._sessions.move_to_end(session_id)
            return mcp

    def end_mcp_session(self, session_id: str | None) -> None:
        with self._sessions_lock:
            self._sessions.pop(session_id or "", None)

    # ------------------------------------------------------------------ lifecycle

    def _watch_idle(self) -> None:
        while True:
            time.sleep(min(30.0, max(self.idle_timeout / 4, 0.05)))
            if time.monotonic() - self._last > self.idle_timeout:
                log.info("idle for %.0f s, stopping", self.idle_timeout)
                self.shutdown()
                return

    def write_run_file(self, root: Path) -> None:
        run = root / "run"
        run.mkdir(parents=True, exist_ok=True)
        self.run_file = run / "server.json"
        info = {"pid": os.getpid(), "url": self.url, "version": __version__, "started": time.time()}
        tmp = self.run_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(info))
        os.replace(tmp, self.run_file)

    def remove_run_file(self) -> None:
        if self.run_file is None:
            return
        try:
            info = json.loads(self.run_file.read_text())
            if info.get("pid") == os.getpid():
                self.run_file.unlink()
        except (OSError, ValueError):
            pass

    def serve(self) -> None:
        if self.idle_timeout > 0:
            threading.Thread(target=self._watch_idle, name="cogito-mem-idle", daemon=True).start()
        if self.memory.root is not None:
            self.write_run_file(self.memory.root)
        try:
            self.serve_forever(poll_interval=0.2)
        finally:
            self.remove_run_file()
            self.server_close()
