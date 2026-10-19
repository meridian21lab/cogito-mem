"""The llama.cpp runtime.

Tests marked ``llama`` need a llama-server binary and a GGUF embedding model:

    COGITO_MEM_TEST_LLAMA_SERVER=/path/to/llama-server \\
    COGITO_MEM_TEST_MODEL=/path/to/embeddinggemma-2-Q8_0.gguf pytest -m llama

Any GGUF of the gemma-embedding2 architecture works, including a tiny random one,
since these tests check the plumbing, not the quality of the vectors.
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pytest
from conftest import LLAMA_MODEL, LLAMA_SERVER, append, query

from cogito_mem import Config, Memory, runtime
from cogito_mem.embedding import DIM, doc_prompt, query_prompt
from cogito_mem.split import split

SRC = str(Path(__file__).resolve().parents[1] / "src")
needs_llama = pytest.mark.skipif(
    not (LLAMA_SERVER and LLAMA_MODEL), reason="set COGITO_MEM_TEST_LLAMA_SERVER and COGITO_MEM_TEST_MODEL"
)


# --------------------------------------------------------------------------- without llama


def test_download_is_atomic(tmp_path):
    src = tmp_path / "model.gguf"
    src.write_bytes(b"GGUF" + os.urandom(3_000_000))
    dest = runtime.download(src.as_uri(), tmp_path / "models" / "m.gguf")
    assert dest.read_bytes() == src.read_bytes()
    assert not list((tmp_path / "models").glob("*.part"))


def test_ensure_model_downloads_once(tmp_path, monkeypatch):
    src = tmp_path / "src.gguf"
    src.write_bytes(b"GGUF-fake")
    monkeypatch.delenv("COGITO_MEM_MODEL", raising=False)
    monkeypatch.delenv("COGITO_MEM_NO_DOWNLOAD", raising=False)
    monkeypatch.setenv("COGITO_MEM_MODEL_URL", src.as_uri())
    root = tmp_path / "home"
    path = runtime.ensure_model(root)
    assert path == root / "models" / runtime.MODEL_FILE and path.read_bytes() == b"GGUF-fake"
    src.unlink()
    assert runtime.ensure_model(root) == path  # no second download
    monkeypatch.setenv("COGITO_MEM_NO_DOWNLOAD", "1")
    with pytest.raises(runtime.RuntimeUnavailable):
        runtime.ensure_model(tmp_path / "other")


def test_release_asset_choice(monkeypatch):
    assets = [{"name": n} for n in (
        "llama-b7000-bin-macos-arm64.tar.gz", "llama-b7000-bin-macos-x64.tar.gz",
        "llama-b7000-bin-ubuntu-x64.tar.gz", "llama-b7000-bin-ubuntu-vulkan-x64.tar.gz",
        "llama-b7000-bin-ubuntu-arm64.zip", "llama-b7000-bin-win-cpu-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip",
    )]  # fmt: skip
    cases = [("Darwin", "arm64", "macos-arm64"), ("Linux", "x86_64", "bin-ubuntu-x64."),
             ("Linux", "aarch64", "ubuntu-arm64"), ("Windows", "AMD64", "win-cpu-x64")]  # fmt: skip
    for system, machine, expect in cases:
        monkeypatch.setattr(runtime.platform, "system", lambda s=system: s)
        monkeypatch.setattr(runtime.platform, "machine", lambda m=machine: m)
        assert expect in runtime._release_asset(assets)["name"]


def _fake_release(tmp_path: Path, archive: str) -> str:
    """A GitHub 'latest release' answer pointing at a local archive with a fake llama-server."""
    script = b"#!/bin/sh\necho fake\n"
    name = "llama-b7000-bin-ubuntu-x64" + archive
    path = tmp_path / name
    if archive == ".zip":
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("build/bin/llama-server", script)
    else:
        with tarfile.open(path, "w:gz") as tf:
            info = tarfile.TarInfo("llama-b7000/llama-server")
            info.size = len(script)
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(script))
    api = tmp_path / "release.json"
    api.write_text(json.dumps({"tag_name": "b7000", "assets": [{"name": name, "browser_download_url": path.as_uri()}]}))
    return api.as_uri()


def test_service_fetches_llama_cpp_on_first_start(tmp_path, monkeypatch):
    """Without llama.cpp (e.g. the Claude Code plugin), the runtime downloads the release itself."""
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "x86_64")
    monkeypatch.delenv("COGITO_MEM_LLAMA_SERVER", raising=False)
    monkeypatch.delenv("COGITO_MEM_NO_DOWNLOAD", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    api = _fake_release(tmp_path, ".zip")
    monkeypatch.setattr(runtime, "LLAMA_RELEASES_API", api)
    monkeypatch.setattr(runtime.install_llama_server, "__defaults__", (api,))
    monkeypatch.setenv("COGITO_MEM_MODEL", str(tmp_path / "no-model.gguf"))
    rt = runtime.LlamaRuntime(tmp_path / "home")
    with pytest.raises(runtime.RuntimeUnavailable, match="no-model.gguf"):  # got llama.cpp, then stopped at the model
        rt.start()
    assert runtime.find_llama_server(tmp_path / "home") is not None


@pytest.mark.parametrize("archive", [".zip", ".tar.gz"])
def test_install_llama_server_from_a_release(tmp_path, monkeypatch, archive):
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "x86_64")
    monkeypatch.delenv("COGITO_MEM_LLAMA_SERVER", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    root = tmp_path / "home"
    binary = runtime.install_llama_server(root, api_url=_fake_release(tmp_path, archive))
    assert binary.name == "llama-server" and os.access(binary, os.X_OK)
    assert runtime.find_llama_server(root) == binary


def test_safe_extract_refuses_path_traversal(tmp_path):
    with pytest.raises(runtime.RuntimeUnavailable):
        runtime._safe_extract(["ok/file", "../../etc/passwd"], tmp_path)


class _FakeRerank(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/v1/rerank"
        docs = body["documents"]
        results = [{"index": i, "relevance_score": (5.0 if "Biscuit" in d else -5.0)} for i, d in enumerate(docs)]
        data = json.dumps({"results": sorted(results, key=lambda r: -r["relevance_score"])}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_reranker_reorders_the_top_candidates():
    srv = HTTPServer(("127.0.0.1", 0), _FakeRerank)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        reranker = runtime.LlamaServerReranker(f"http://127.0.0.1:{srv.server_address[1]}", "fake-reranker")
        scores = reranker.score("dog name", ["a beagle called Biscuit", "a cat"])
        assert scores[0] > 0.99 and scores[1] < 0.01  # logits are mapped to [0, 1]
        with Memory(None, embedder="hash", reranker=reranker) as m:
            append(m, {"author": "u", "text": "dog name ideas: Rex, Max"}, {"author": "u", "text": "My dog is called Biscuit"})
            m.flush(10)
            items = query(m, "dog name")["items"]
            assert items[0]["text"] == "My dog is called Biscuit" and items[0]["score"] > 0.99
            assert [i["score"] for i in items] == sorted((i["score"] for i in items), reverse=True)
            assert m.status()["reranker"] == "fake-reranker"
    finally:
        srv.shutdown()


def test_missing_runtime_leaves_keyword_search(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    monkeypatch.setenv("COGITO_MEM_NO_DOWNLOAD", "1")
    monkeypatch.delenv("COGITO_MEM_LLAMA_SERVER", raising=False)
    with Memory(tmp_path / "home") as m:
        assert m.wait_until_ready(30) is False
        assert m.status()["embedder"]["state"].startswith("unavailable: llama-server was not found")
        append(m, {"author": "u", "text": "keyword only still works"})
        assert query(m, "keyword")["items"][0]["text"] == "keyword only still works"


# --------------------------------------------------------------------------- with llama


@pytest.fixture(scope="module")
def llama():
    if not (LLAMA_SERVER and LLAMA_MODEL):
        pytest.skip("set COGITO_MEM_TEST_LLAMA_SERVER and COGITO_MEM_TEST_MODEL")
    server = runtime.LlamaServer(Path(LLAMA_SERVER), Path(LLAMA_MODEL), ["--embedding"])
    server.start()
    yield server
    server.stop()


@needs_llama
@pytest.mark.llama
def test_llama_tokenizer_offsets(llama):
    tok = runtime.LlamaServerTokenizer(llama.base, "m")
    for text in ["Hello world, ünïcödé 你好 🦙 done", "a b\n\ttab", " leading space", "x" * 50, "plain ascii text"]:
        ends = tok.offsets(text)
        assert ends == sorted(ends) and ends[-1] == len(text) and 0 < ends[0]
    assert tok.offsets("") == []


@needs_llama
@pytest.mark.llama
def test_llama_embeddings(llama):
    emb = runtime.LlamaServerEmbedder(llama.base, "m")
    prompts = [doc_prompt(None, "the cat sat on the mat"), query_prompt("where did the cat sit?"), doc_prompt("t", "x")]
    batch = emb.embed(prompts)
    assert batch.shape == (3, DIM) and np.allclose(np.linalg.norm(batch, axis=1), 1.0, atol=2e-3)
    single = emb.embed(prompts[:1])
    assert np.allclose(single[0], batch[0], atol=2e-3)
    assert not np.allclose(batch[0], batch[1], atol=1e-2)
    huge = doc_prompt(None, "word " * 5000)  # more than one slot holds: cut to fit
    assert emb.embed([huge]).shape == (1, DIM)


@needs_llama
@pytest.mark.llama
def test_memory_on_llama_cpp(tmp_path, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_LLAMA_SERVER", LLAMA_SERVER)
    monkeypatch.setenv("COGITO_MEM_MODEL", LLAMA_MODEL)
    with Memory(tmp_path / "home", config=Config(search="vector")) as m:
        assert m.wait_until_ready(120)
        assert m.status()["embedder"]["name"] == Path(LLAMA_MODEL).name
        text = "\n\n".join(f"Part {i}. " + "Budgets and costs grow every quarter. " * 25 for i in range(5))
        r = append(m, {"author": "a", "text": text}, {"author": "b", "text": "a short note"})["items"]
        assert r[0]["pieces"] > 1
        for span in split(text, m.tokenizer):
            assert span.tokens <= 256
            assert len(m.tokenizer.offsets(text[span.start : span.end])) <= 256
        assert m.flush(60)
        resp = query(m, "costs", max_tokens=100, top_k=100)
        assert resp["tokens"] <= 100 and resp["items"]
        assert (tmp_path / "home" / "run" / "llama-server.log").exists()


@needs_llama
@pytest.mark.llama
def test_external_llama_server_url(llama, tmp_path, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_LLAMA_SERVER", llama.base)
    with Memory(tmp_path / "home") as m:
        assert m.wait_until_ready(30)
        assert m.embedder.name == Path(LLAMA_MODEL).name  # read from /props
        append(m, {"author": "a", "text": "through an external server"})
        assert m.flush(30)


@needs_llama
@pytest.mark.llama
def test_llama_server_dies_with_its_parent(tmp_path):
    code = (
        "import sys, time; sys.path.insert(0, %r)\n"
        "from pathlib import Path\n"
        "from cogito_mem import runtime\n"
        "s = runtime.LlamaServer(Path(%r), Path(%r), ['--embedding'])\n"
        "s.start()\n"
        "print(s.port, flush=True)\n"
        "time.sleep(600)\n"
    ) % (SRC, LLAMA_SERVER, LLAMA_MODEL)
    parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    port = int(parent.stdout.readline())
    status, _ = runtime._get(f"http://127.0.0.1:{port}", "/health")
    assert status == 200
    parent.send_signal(signal.SIGKILL)  # no cleanup code runs in the parent
    parent.wait()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            runtime._get(f"http://127.0.0.1:{port}", "/health", timeout=1)
        except OSError:
            return  # the watchdog stopped llama-server
        time.sleep(0.3)
    pytest.fail("llama-server outlived its parent")
