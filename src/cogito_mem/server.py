"""The local service: ``POST /v1/memory`` on localhost (requirements §3).

One warm process holds the memory and the embedding model; the MCP bridge, the
capture hooks and the command line all talk to it. It binds to 127.0.0.1 only,
answers only requests whose Host is local and whose body is JSON (so a web page
cannot write to it), and exits after an idle period; clients start it again on
demand.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .errors import ApiError
from .memory import Memory

log = logging.getLogger("cogito_mem")

DEFAULT_PORT = 7327
MAX_BODY = 64 * 1024 * 1024
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def default_port() -> int:
    return int(os.environ.get("COGITO_MEM_PORT", DEFAULT_PORT))


class _Handler(BaseHTTPRequestHandler):
    server_version = f"cogito-mem/{__version__}"
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True  # headers and body go out at once, not 40 ms apart
    server: "MemoryServer"

    def log_message(self, fmt: str, *args) -> None:
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, err: ApiError) -> None:
        self._send(err.http_status, err.body())

    def _local_host(self) -> bool:
        host = self.headers.get("Host")
        if host is None:
            return True
        if host.startswith("["):
            name = host.split("]")[0] + "]"
        else:
            name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        return name.lower() in _LOCAL_HOSTS

    def do_GET(self) -> None:  # noqa: N802
        self.server.touch()
        if not self._local_host():
            return self._error(ApiError("permission_denied", "only local requests are served"))
        if self.path.split("?")[0] == "/v1/status":
            return self._send(200, {"status": "ok", "pid": os.getpid(), **self.server.memory.status()})
        self._error(ApiError("not_found", f"no such path: {self.path}"))

    def do_POST(self) -> None:  # noqa: N802
        self.server.touch()
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            self.close_connection = True
            return self._error(ApiError("invalid_argument", f"Content-Length must be 0 to {MAX_BODY} bytes"))
        raw = self.rfile.read(length)
        if not self._local_host():
            return self._error(ApiError("permission_denied", "only local requests are served"))
        if self.path.split("?")[0] != "/v1/memory":
            return self._error(ApiError("not_found", f"no such path: {self.path}; use POST /v1/memory"))
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._error(ApiError("invalid_argument", "Content-Type must be application/json"))
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

    def do_OPTIONS(self) -> None:  # noqa: N802 - no CORS: browsers may not call this service
        self._error(ApiError("permission_denied", "cross-origin requests are not served"))


class MemoryServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, memory: Memory, host: str = "127.0.0.1", port: int = DEFAULT_PORT, idle_timeout: float = 0):
        super().__init__((host, port), _Handler)
        self.memory = memory
        self.idle_timeout = idle_timeout
        self._last = time.monotonic()
        self.run_file: Path | None = None

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"

    def touch(self) -> None:
        self._last = time.monotonic()

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
