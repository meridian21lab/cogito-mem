"""A client for the local service that starts it when it is not running.

It imports nothing heavy, so the capture hooks and the MCP bridge start fast.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import ApiError

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
START_TIMEOUT = 60.0


def default_root() -> Path:
    env = os.environ.get("COGITO_MEM_HOME")
    return Path(env).expanduser() if env else Path.home() / ".cogito-mem"


def default_port() -> int:
    return int(os.environ.get("COGITO_MEM_PORT", 7327))


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.1)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


class Client:
    """Sends request dictionaries to ``POST /v1/memory`` and returns the response dictionary."""

    def __init__(
        self,
        url: str | None = None,
        root: str | Path | None = None,
        autostart: bool = True,
        timeout: float = 120.0,
        serve_args: list[str] | None = None,
    ):
        self.root = Path(root).expanduser() if root is not None else default_root()
        self.explicit_url = url or os.environ.get("COGITO_MEM_URL")
        self.autostart = autostart and not self.explicit_url
        self.timeout = timeout
        self.serve_args = serve_args or []

    @property
    def url(self) -> str:
        if self.explicit_url:
            return self.explicit_url.rstrip("/")
        run_file = self.root / "run" / "server.json"
        try:
            return json.loads(run_file.read_text())["url"]
        except (OSError, ValueError, KeyError):
            return f"http://127.0.0.1:{default_port()}"

    # ------------------------------------------------------------------ requests

    def _request(self, method: str, path: str, body: Any = None, timeout: float | None = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with _opener.open(req, timeout=timeout or self.timeout) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, {"error": {"code": "internal", "message": raw.decode("utf-8", "replace")}}

    def handle(self, body: dict) -> dict:
        try:
            status, resp = self._request("POST", "/v1/memory", body)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            if not self.autostart:
                raise ApiError("unavailable", f"the cogito-mem service is not running at {self.url}") from None
            self.start_server()
            status, resp = self._request("POST", "/v1/memory", body)
        if status != 200:
            err = (resp or {}).get("error", {}) if isinstance(resp, dict) else {}
            code = err.get("code", "internal")
            try:
                raise ApiError(code, err.get("message", f"HTTP {status}"))
            except ValueError:
                raise ApiError("internal", f"HTTP {status}: {err}") from None
        return resp

    def append(self, items: list[dict], namespace: str = "default", import_: bool = False) -> dict:
        return self.handle({"op": "append", "namespace": namespace, "import": import_, "items": items})

    def query(self, text: str, namespace: str = "default", **kwargs: Any) -> dict:
        return self.handle({"op": "query", "namespace": namespace, "text": text, **kwargs})

    def status(self) -> dict | None:
        try:
            status, resp = self._request("GET", "/v1/status", timeout=5)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            return None
        return resp if status == 200 else None

    # ------------------------------------------------------------------ the service

    def start_server(self) -> None:
        """Start ``cogito-mem serve`` in the background, unless another client just did."""
        with _file_lock(self.root / "run" / "start.lock"):
            if self.status() is not None:
                return
            run = self.root / "run"
            run.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, "-m", "cogito_mem", "serve", "--root", str(self.root), *self.serve_args]
            kwargs: dict[str, Any] = {}
            if os.name == "nt":
                kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            with open(run / "server.log", "ab") as out:
                proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, **kwargs)
            deadline = time.monotonic() + START_TIMEOUT
            while time.monotonic() < deadline:
                if self.status() is not None:
                    return
                if proc.poll() is not None and self.status() is None:
                    raise ApiError(
                        "unavailable", f"cogito-mem serve exited with code {proc.returncode}; see {run / 'server.log'}"
                    )
                time.sleep(0.1)
            raise ApiError("unavailable", f"cogito-mem serve did not start within {START_TIMEOUT:.0f} s")

    def stop_server(self) -> bool:
        info = self.status()
        if info is None:
            return False
        pid = info.get("pid")
        if not pid:
            return False
        import signal

        os.kill(int(pid), signal.SIGTERM)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and self.status() is not None:
            time.sleep(0.1)
        return True
