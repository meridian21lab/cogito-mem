"""Install and uninstall for each client, in a fake HOME."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cogito_mem.install import install, uninstall

SRC = str(Path(__file__).resolve().parents[1] / "src")

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None


def run_install(client: str, root: Path, **kw) -> list[str]:
    lines: list[str] = []
    assert install(client, root, say=lines.append, download=False, start=False, **kw) == 0
    return lines


def test_install_claude_code_without_cli(isolated_env, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_NO_CLAUDE_CLI", "1")
    home = isolated_env
    root = home / ".cogito-mem"
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    their_hook = {"matcher": "", "hooks": [{"type": "command", "command": "echo theirs"}]}
    settings.write_text(json.dumps({"model": "opus", "hooks": {"Stop": [their_hook]}}))

    run_install("claude-code", root)
    run_install("claude-code", root)  # twice: nothing is doubled

    launcher = root / "bin" / "cogito-mem"
    assert launcher.exists() and os.access(launcher, os.X_OK)
    assert (root / "memory" / "default" / "log.sqlite3").exists()
    cfg = json.loads((home / ".claude.json").read_text())
    assert cfg["mcpServers"]["cogito-mem"] == {"type": "stdio", "command": str(launcher), "args": ["mcp"], "env": {}}
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    assert data["hooks"]["Stop"][0] == their_hook
    assert len(data["hooks"]["Stop"]) == 2 and len(data["hooks"]["SessionEnd"]) == 1
    ours = data["hooks"]["Stop"][1]["hooks"][0]
    assert ours["command"] == f"{launcher} capture claude-code"
    assert (settings.parent / "settings.json.cogito-mem.bak").exists()

    uninstall("claude-code", root, say=lambda s: None)
    data = json.loads(settings.read_text())
    assert data == {"model": "opus", "hooks": {"Stop": [their_hook]}}
    assert "cogito-mem" not in json.loads((home / ".claude.json").read_text()).get("mcpServers", {})
    assert (root / "memory" / "default" / "log.sqlite3").exists()  # the memory is kept


@pytest.mark.skipif(shutil.which("claude") is None, reason="the claude CLI is not installed")
def test_install_claude_code_with_the_claude_cli(isolated_env):
    home = isolated_env
    root = home / ".cogito-mem"
    lines = run_install("claude-code", root)
    assert not any("failed" in line for line in lines), lines
    cfg = json.loads((home / ".claude.json").read_text())
    assert cfg["mcpServers"]["cogito-mem"]["command"] == str(root / "bin" / "cogito-mem")
    assert cfg["mcpServers"]["cogito-mem"]["args"] == ["mcp"]
    uninstall("claude-code", root, say=lambda s: None)
    assert "cogito-mem" not in json.loads((home / ".claude.json").read_text()).get("mcpServers", {})


def test_install_codex_keeps_the_users_config(isolated_env):
    home = isolated_env
    root = home / ".cogito-mem"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir()
    original = 'model = "gpt-5-codex"\n\n[mcp_servers.other]\ncommand = "other-server"\n'
    config.write_text(original)
    run_install("codex", root)
    run_install("codex", root)
    text = config.read_text()
    assert text.count("[mcp_servers.cogito-mem]") == 1 and text.count("notify = ") == 1
    if tomllib:
        data = tomllib.loads(text)
        launcher = str(root / "bin" / "cogito-mem")
        assert data["notify"] == [launcher, "capture", "codex"]
        assert data["mcp_servers"]["cogito-mem"] == {"command": launcher, "args": ["mcp"]}
        assert data["mcp_servers"]["other"] == {"command": "other-server"}
        assert data["model"] == "gpt-5-codex"
    uninstall("codex", root, say=lambda s: None)
    assert config.read_text() == original


def test_install_codex_does_not_replace_an_existing_notify(isolated_env):
    home = isolated_env
    config = home / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('notify = ["my-notifier"]\n')
    lines = run_install("codex", home / ".cogito-mem")
    assert any("already sets notify" in line for line in lines)
    text = config.read_text()
    assert text.count("notify") == 1 + text.count("cogito-mem notify")  # only theirs is a setting
    if tomllib:
        assert tomllib.loads(text)["notify"] == ["my-notifier"]


def test_install_claude_desktop(isolated_env):
    home = isolated_env
    path = home / "claude_desktop_config.json"
    path.write_text(json.dumps({"mcpServers": {"fs": {"command": "fs-server"}}, "theme": "dark"}))
    run_install("claude-desktop", home / ".cogito-mem")
    data = json.loads(path.read_text())
    assert data["mcpServers"]["cogito-mem"] == {"command": str(home / ".cogito-mem" / "bin" / "cogito-mem"), "args": ["mcp"]}
    assert data["mcpServers"]["fs"] == {"command": "fs-server"} and data["theme"] == "dark"
    uninstall("claude-desktop", home / ".cogito-mem", say=lambda s: None)
    assert json.loads(path.read_text()) == {"mcpServers": {"fs": {"command": "fs-server"}}, "theme": "dark"}


def test_unknown_client(isolated_env):
    lines: list[str] = []
    assert install("vim", isolated_env / ".cogito-mem", say=lines.append, download=False, start=False) == 2


def test_launcher_runs_cogito_mem(isolated_env):
    run_install("claude-desktop", isolated_env / ".cogito-mem")
    launcher = isolated_env / ".cogito-mem" / "bin" / "cogito-mem"
    out = subprocess.run([str(launcher), "--version"], capture_output=True, text=True, timeout=30,
                         env={**os.environ, "PYTHONPATH": SRC})  # fmt: skip
    assert out.returncode == 0 and out.stdout.startswith("cogito-mem ")
    assert sys.executable in launcher.read_text()
