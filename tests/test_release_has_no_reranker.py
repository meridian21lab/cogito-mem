"""What we release runs plain hybrid search: the plugin, the package and the image never bring a reranker.

This keeps installing simple. A reranker stays a manual option (``--reranker``, ``COGITO_MEM_RERANKER``) for whoever
sets it up, and for the evals; its results are in ``evals/baselines/long-history-20261101/README.md``.

The release workflow runs this file on the built package before it publishes, with ``COGITO_MEM_CHECK_DIST`` naming the
folder of built files. To change the decision, change this file on purpose.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from cogito_mem import Memory
from cogito_mem.cli import build_parser

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "cogito_mem"
# Turning a reranker on, or naming a model for one. The word alone is fine where a file only reports on it.
TURNS_IT_ON = re.compile(r"COGITO_MEM_RERANKER|--reranker|qwen|rerank\S*\.gguf", re.IGNORECASE)
# What people get with the release, beyond the package: how it installs, what it runs, what it starts with.
RELEASE_FILES = [
    "Dockerfile",
    "pyproject.toml",
    "server.json",
    ".claude-plugin/marketplace.json",
    ".github/workflows/release.yml",
    ".github/workflows/docker.yml",
    "scripts/pin_plugin.py",
]
# The only code that may read the setting and start the model. Evals pass their own --reranker.
MAY_START_IT = {"cli.py", "runtime.py"}


def test_the_plugin_folder_knows_nothing_of_a_reranker():
    # The plugin folder is all that people who install it get: hooks, MCP server, settings, lock file.
    found = []
    for path in (REPO / "plugin").rglob("*"):
        if path.is_file() and path.suffix != ".png":
            found += [f"{path.relative_to(REPO)}: {m.group()}" for m in re.finditer(r"rerank|qwen", path.read_text(encoding="utf-8"), re.IGNORECASE)]
    assert not found, found


def test_the_plugin_holds_no_model():
    assert not [p for p in (REPO / "plugin").rglob("*") if p.suffix == ".gguf"]


@pytest.mark.parametrize("name", RELEASE_FILES)
def test_release_files_do_not_turn_it_on(name):
    found = TURNS_IT_ON.findall((REPO / name).read_text(encoding="utf-8"))
    assert not found, f"{name}: {found}"


def test_only_the_explicit_option_starts_it():
    found = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        if rel.parts[0] == "evals" or rel.name in MAY_START_IT:
            continue
        found += [f"{rel}: {m}" for m in re.findall(r"COGITO_MEM_RERANKER|start_reranker", path.read_text(encoding="utf-8"))]
    assert not found, found


def test_no_code_knows_where_to_download_one():
    found = []
    for path in SRC.rglob("*.py"):
        found += [f"{path.relative_to(SRC)}: {u}" for u in re.findall(r"https?://\S*(?:rerank|qwen)\S*", path.read_text(encoding="utf-8"), re.IGNORECASE)]
    assert not found, found


def test_nothing_is_set_by_default():
    assert build_parser().parse_args(["serve"]).reranker is None
    assert inspect.signature(Memory.__init__).parameters["reranker"].default is None


def test_the_service_starts_without_one(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k != "COGITO_MEM_RERANKER"}
    env["PYTHONPATH"] = str(REPO / "src")
    proc = subprocess.Popen(
        [sys.executable, "-m", "cogito_mem", "--root", str(tmp_path / "h"), "serve", "--embedder", "hash", "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        status = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/status", timeout=2) as resp:
                    status = json.load(resp)
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.2)
        assert status is not None, "the service did not start"
        assert status["reranker"] is None
    finally:
        proc.kill()
        proc.wait()


def test_the_built_package_holds_no_model():
    folder = os.environ.get("COGITO_MEM_CHECK_DIST")
    if not folder:
        pytest.skip("runs in the release, on what it built")
    built = [p for p in Path(folder).iterdir() if p.suffix == ".whl" or p.name.endswith(".tar.gz")]
    assert built, f"nothing built in {folder}"
    for path in built:
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
        else:
            with tarfile.open(path) as t:
                names = t.getnames()
        assert not [n for n in names if n.endswith(".gguf")], path.name
