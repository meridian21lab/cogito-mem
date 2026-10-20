from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cogito_mem import Memory  # noqa: E402


@pytest.fixture
def mem():
    m = Memory(None, embedder="hash")
    yield m
    m.close()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "cogito-home"


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake HOME so nothing touches the real ~/.claude, ~/.codex or ~/.cogito-mem."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for var in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "COGITO_MEM_HOME", "COGITO_MEM_URL", "COGITO_MEM_PORT",
                "CLAUDE_CODE_SESSION_ID", "COGITO_MEM_THREAD_ID", "COGITO_MEM_NAMESPACE"):
        monkeypatch.delenv(var, raising=False)
    for var in ("LOGNAME", "USER", "LNAME", "USERNAME"):  # the memory is then named ksirg-hollow
        monkeypatch.setenv(var, "ksirg")
    monkeypatch.setenv("COGITO_MEM_CLAUDE_DESKTOP_CONFIG", str(home / "claude_desktop_config.json"))
    return home


def append(m: Memory, *items: dict, namespace: str = "default", import_: bool = False) -> dict:
    return m.handle({"op": "append", "namespace": namespace, "import": import_, "items": list(items)})


def query(m: Memory, text: str, **kw) -> dict:
    return m.handle({"op": "query", "text": text, **kw})


LLAMA_SERVER = os.environ.get("COGITO_MEM_TEST_LLAMA_SERVER")
LLAMA_MODEL = os.environ.get("COGITO_MEM_TEST_MODEL")
