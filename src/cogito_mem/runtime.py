"""The llama.cpp runtime: EmbeddingGemma 2 served by ``llama-server``.

The memory talks to llama.cpp's own HTTP server rather than to Python bindings,
so it can use a model architecture the day llama.cpp supports it, and so Metal
or CUDA builds work without recompiling anything here.

Where things come from (first match wins):

- the model: ``COGITO_MEM_MODEL`` (a path), else ``<root>/models/embeddinggemma-2-Q8_0.gguf``,
  downloaded from ``COGITO_MEM_MODEL_URL`` (default: ggml-org on Hugging Face) on first use;
- the server: ``COGITO_MEM_LLAMA_SERVER`` (a binary path, or the URL of a running
  server), else ``llama-server`` on the PATH, else the copy ``cogito-mem install``
  put in ``<root>/bin/llama.cpp``.

``COGITO_MEM_GPU_LAYERS`` (``-ngl``) and ``COGITO_MEM_THREADS`` (``-t``) are passed
through; ``COGITO_MEM_GPU_LAYERS=0`` runs on the CPU only.
"""

from __future__ import annotations

import atexit
import bisect
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Sequence

import numpy as np

from .embedding import finish, profile_for

log = logging.getLogger("cogito_mem")

MODEL_FILE = "embeddinggemma-2-Q8_0.gguf"
MODEL_URL = f"https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/main/{MODEL_FILE}"
LLAMA_RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

SLOT_CONTEXT = 2048  # tokens per input; llama.cpp embeds one input in one batch
PARALLEL = 4
MAX_INPUT_TOKENS = SLOT_CONTEXT - 8
START_TIMEOUT = 180.0


class RuntimeUnavailable(RuntimeError):
    pass


# --------------------------------------------------------------------------- HTTP


def _post(base: str, path: str, body: dict, timeout: float = 120.0) -> object:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise LlamaServerError(exc.code, detail) from None


def _get(base: str, path: str, timeout: float = 5.0) -> tuple[int, object]:
    try:
        with _opener.open(base + path, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None


# The local server must never go through an HTTP proxy.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class LlamaServerError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"llama-server returned HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


# --------------------------------------------------------------------------- tokenizer and embedder


class LlamaServerTokenizer:
    """Token offsets from llama-server's ``/tokenize`` (the model's own tokenizer)."""

    def __init__(self, base: str, name: str):
        self.base = base
        self.name = name

    def offsets(self, text: str) -> list[int]:
        if not text:
            return []
        res = _post(self.base, "/tokenize", {"content": text, "add_special": False, "with_pieces": True})
        tokens = res["tokens"]  # type: ignore[index]
        byte_ends = []
        pos = 0
        for tok in tokens:
            piece = tok["piece"]
            pos += len(piece.encode("utf-8")) if isinstance(piece, str) else len(piece)
            byte_ends.append(pos)
        if text.isascii():
            n = len(text)
            if pos == n:
                return byte_ends
            return [min(n, round(b * n / max(pos, 1))) for b in byte_ends]
        char_ends = []
        acc = 0
        for ch in text:
            acc += len(ch.encode("utf-8"))
            char_ends.append(acc)
        if pos != acc:  # should not happen; keep counts right and spans close
            byte_ends = [round(b * acc / max(pos, 1)) for b in byte_ends]
        return [bisect.bisect_right(char_ends, b) for b in byte_ends]


class LlamaServerEmbedder:
    def __init__(self, base: str, name: str):
        self.base = base
        self.name = name
        self.tokenizer = LlamaServerTokenizer(base, name)
        self.profile = profile_for(name)

    def _fit(self, prompt: str) -> str:
        ends = self.tokenizer.offsets(prompt)
        if len(ends) <= MAX_INPUT_TOKENS:
            return prompt
        return prompt[: ends[MAX_INPUT_TOKENS - 1]]

    def embed(self, prompts: Sequence[str]) -> np.ndarray:
        prompts = list(prompts)
        try:
            res = _post(self.base, "/v1/embeddings", {"input": prompts, "encoding_format": "float"})
        except LlamaServerError as exc:
            if "too large" not in exc.detail:
                raise
            prompts = [self._fit(p) for p in prompts]
            res = _post(self.base, "/v1/embeddings", {"input": prompts, "encoding_format": "float"})
        data = sorted(res["data"], key=lambda d: d["index"])  # type: ignore[index]
        return finish(np.array([d["embedding"] for d in data], dtype=np.float32))


class LlamaServerReranker:
    """A cross-encoder reranker (stage-0 arm R) served by ``llama-server --reranking``."""

    def __init__(self, base: str, name: str):
        self.base = base
        self.name = name

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        res = _post(self.base, "/v1/rerank", {"query": query, "documents": list(texts), "top_n": len(texts)})
        scores = [0.0] * len(texts)
        for r in res["results"]:  # type: ignore[index]
            s = float(r["relevance_score"])
            scores[r["index"]] = s if 0.0 <= s <= 1.0 else float(1.0 / (1.0 + np.exp(-s)))
        return scores


# --------------------------------------------------------------------------- process management

_WATCHDOG = r"""
import os, subprocess, sys, time, signal
parent = int(sys.argv[1])
child = subprocess.Popen(sys.argv[2:])
def stop(*_):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(10)
        except subprocess.TimeoutExpired:
            child.kill()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
def parent_alive():
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, parent)
        if not h:
            return False
        r = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
        ctypes.windll.kernel32.CloseHandle(h)
        return r != 0
    return os.getppid() == parent
while child.poll() is None:
    if not parent_alive():
        stop()
    time.sleep(1)
sys.exit(child.returncode or 0)
"""


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LlamaServer:
    """A ``llama-server`` child process, stopped when this process exits (even if killed)."""

    def __init__(self, binary: Path, model: Path, extra: Sequence[str] = (), log_path: Path | None = None):
        self.binary = binary
        self.model = model
        self.extra = list(extra)
        self.log_path = log_path
        self.port = 0
        self.proc: subprocess.Popen | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def command(self) -> list[str]:
        cmd = [
            str(self.binary),
            "-m", str(self.model),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "-c", str(SLOT_CONTEXT * PARALLEL),
            "-b", str(SLOT_CONTEXT),
            "-ub", str(SLOT_CONTEXT),
            "--parallel", str(PARALLEL),
        ]  # fmt: skip
        if os.environ.get("COGITO_MEM_GPU_LAYERS"):
            cmd += ["-ngl", os.environ["COGITO_MEM_GPU_LAYERS"]]
        if os.environ.get("COGITO_MEM_THREADS"):
            cmd += ["-t", os.environ["COGITO_MEM_THREADS"]]
        return cmd + self.extra

    def start(self, timeout: float = START_TIMEOUT) -> None:
        self.port = free_port()
        env = dict(os.environ)
        libdir = str(self.binary.parent)
        for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            env[var] = libdir + (os.pathsep + env[var] if env.get(var) else "")
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            out = open(self.log_path, "ab")
        else:
            out = subprocess.DEVNULL
        self.proc = subprocess.Popen(
            [sys.executable, "-c", _WATCHDOG, str(os.getpid()), *self.command()],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            env=env,
        )
        atexit.register(self.stop)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeUnavailable(
                    f"llama-server exited with code {self.proc.returncode}"
                    + (f"; see {self.log_path}" if self.log_path else "")
                )
            try:
                status, _ = _get(self.base, "/health", timeout=2)
                if status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.2)
        self.stop()
        raise RuntimeUnavailable(f"llama-server did not become healthy within {timeout:.0f} s")

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()


# --------------------------------------------------------------------------- discovery and downloads


def _progress(label: str, done: int, total: int) -> None:
    if not sys.stderr.isatty():
        return
    if total:
        sys.stderr.write(f"\r{label}: {done / 1e6:.0f} / {total / 1e6:.0f} MB")
    else:
        sys.stderr.write(f"\r{label}: {done / 1e6:.0f} MB")
    sys.stderr.flush()


def download(url: str, dest: Path, label: str | None = None) -> Path:
    """Download ``url`` to ``dest`` atomically (through the system's HTTPS proxy, if any)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    label = label or dest.name
    req = urllib.request.Request(url, headers={"User-Agent": "cogito-mem"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            _progress(label, done, total)
    if sys.stderr.isatty():
        sys.stderr.write("\n")
    if total and done != total:
        part.unlink(missing_ok=True)
        raise RuntimeUnavailable(f"download of {url} stopped at {done} of {total} bytes")
    os.replace(part, dest)
    return dest


def model_path(root: Path | None) -> Path:
    env = os.environ.get("COGITO_MEM_MODEL")
    if env:
        return Path(env).expanduser()
    base = root if root is not None else Path.home() / ".cogito-mem"
    return base / "models" / MODEL_FILE


def ensure_model(root: Path | None, allow_download: bool = True) -> Path:
    path = model_path(root)
    if path.exists():
        return path
    if os.environ.get("COGITO_MEM_MODEL"):
        raise RuntimeUnavailable(f"COGITO_MEM_MODEL points to {path}, which does not exist")
    if os.environ.get("COGITO_MEM_NO_DOWNLOAD"):
        raise RuntimeUnavailable(f"the embedding model is not at {path} and COGITO_MEM_NO_DOWNLOAD is set")
    if not allow_download:
        raise RuntimeUnavailable(f"the embedding model is not at {path}; run `cogito-mem install`")
    url = os.environ.get("COGITO_MEM_MODEL_URL", MODEL_URL)
    log.info("downloading %s", url)
    return download(url, path, label="EmbeddingGemma 2")


def _local_llama_dir(root: Path | None) -> Path:
    base = root if root is not None else Path.home() / ".cogito-mem"
    return base / "bin" / "llama.cpp"


def find_llama_server(root: Path | None) -> Path | None:
    env = os.environ.get("COGITO_MEM_LLAMA_SERVER")
    if env and not env.startswith(("http://", "https://")):
        path = Path(env).expanduser()
        return path if path.exists() else None
    found = shutil.which("llama-server")
    if found:
        return Path(found)
    pointer = _local_llama_dir(root) / "current"
    if pointer.exists():
        path = Path(pointer.read_text().strip())
        if path.exists():
            return path
    return None


def _release_asset(assets: list[dict]) -> dict | None:
    system = platform.system()
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Darwin":
        wanted = ["bin-macos-arm64"] if arm else ["bin-macos-x64"]
    elif system == "Linux":
        wanted = ["bin-ubuntu-arm64"] if arm else ["bin-ubuntu-x64"]
    elif system == "Windows":
        wanted = ["bin-win-cpu-arm64"] if arm else ["bin-win-cpu-x64"]
    else:
        return None
    for asset in assets:
        name = asset.get("name", "")
        if any(w + "." in name for w in wanted) and name.endswith((".zip", ".tar.gz")):
            return asset
    return None


def install_llama_server(root: Path, api_url: str = LLAMA_RELEASES_API) -> Path:
    """Download llama.cpp's latest prebuilt release for this machine into ``<root>/bin/llama.cpp``."""
    req = urllib.request.Request(api_url, headers={"User-Agent": "cogito-mem", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.loads(resp.read())
    asset = _release_asset(release.get("assets", []))
    if asset is None:
        raise RuntimeUnavailable(
            f"no prebuilt llama.cpp for {platform.system()} {platform.machine()}; install llama.cpp yourself"
        )
    tag = release.get("tag_name", "latest")
    target = _local_llama_dir(root) / tag
    archive = download(asset["browser_download_url"], _local_llama_dir(root) / asset["name"], label="llama.cpp")
    target.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            _safe_extract(zf.namelist(), target)
            zf.extractall(target)
    else:
        with tarfile.open(archive) as tf:
            _safe_extract(tf.getnames(), target)
            if hasattr(tarfile, "data_filter"):
                tf.extractall(target, filter="data")
            else:
                tf.extractall(target)
    archive.unlink(missing_ok=True)
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    matches = sorted(target.rglob(exe))
    if not matches:
        raise RuntimeUnavailable(f"the llama.cpp release {tag} has no {exe}")
    binary = matches[0]
    binary.chmod(binary.stat().st_mode | 0o111)
    (_local_llama_dir(root) / "current").write_text(str(binary))
    return binary


def _safe_extract(names: Sequence[str], target: Path) -> None:
    root = target.resolve()
    for name in names:
        dest = (target / name).resolve()
        if root != dest and root not in dest.parents:
            raise RuntimeUnavailable(f"refusing to extract {name!r} outside {target}")


class LlamaRuntime:
    """Starts (or connects to) llama-server for the embedding model and, optionally, a reranker."""

    def __init__(self, root: Path | None, url: str | None = None):
        self.root = root
        self.url = url
        self.server: LlamaServer | None = None
        self._name = MODEL_FILE

    @classmethod
    def from_environment(cls, root: Path | None) -> "LlamaRuntime":
        env = os.environ.get("COGITO_MEM_LLAMA_SERVER", "")
        return cls(root, env.rstrip("/") if env.startswith(("http://", "https://")) else None)

    def start(self) -> None:
        if self.url is not None:
            status, _ = _get(self.url, "/health")
            if status != 200:
                raise RuntimeUnavailable(f"llama-server at {self.url} is not healthy (HTTP {status})")
            _, props = _get(self.url, "/props")
            if isinstance(props, dict) and props.get("model_path"):
                self._name = Path(str(props["model_path"])).name
            return
        binary = find_llama_server(self.root)
        if binary is None and self.root is not None and not os.environ.get("COGITO_MEM_NO_DOWNLOAD"):
            try:  # first start without llama.cpp (e.g. the Claude Code plugin): get the prebuilt release
                binary = install_llama_server(self.root)
            except Exception as exc:
                log.warning("could not download llama.cpp: %s", exc)
        if binary is None:
            raise RuntimeUnavailable(
                "llama-server was not found; run `cogito-mem install`, install llama.cpp "
                "(e.g. `brew install llama.cpp`), or set COGITO_MEM_LLAMA_SERVER"
            )
        model = ensure_model(self.root)
        self._name = model.name
        log_path = self.root / "run" / "llama-server.log" if self.root is not None else None
        self.server = LlamaServer(binary, model, ["--embedding"], log_path)
        self.server.start()

    @property
    def base(self) -> str:
        if self.url is not None:
            return self.url
        assert self.server is not None
        return self.server.base

    def embedder(self) -> LlamaServerEmbedder:
        return LlamaServerEmbedder(self.base, self._name)

    def stop(self) -> None:
        if self.server is not None:
            self.server.stop()
            self.server = None


def start_reranker(spec: str, root: Path | None) -> tuple[LlamaServerReranker, LlamaServer | None]:
    """``spec`` is a reranker GGUF path or the URL of a llama-server started with ``--reranking``."""
    if spec.startswith(("http://", "https://")):
        return LlamaServerReranker(spec.rstrip("/"), spec), None
    binary = find_llama_server(root)
    if binary is None:
        raise RuntimeUnavailable("llama-server was not found for the reranker")
    model = Path(spec).expanduser()
    if not model.exists():
        raise RuntimeUnavailable(f"reranker model {model} does not exist")
    log_path = root / "run" / "llama-reranker.log" if root is not None else None
    server = LlamaServer(binary, model, ["--reranking"], log_path)
    server.start()
    return LlamaServerReranker(server.base, model.name), server
