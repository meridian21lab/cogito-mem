"""Install and uninstall for each client, in a fake HOME."""

from __future__ import annotations

import json
import os
import re
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
    assert (root / "memory" / "ksirg-hollow" / "log.sqlite3").exists()
    assert json.loads((root / "config.json").read_text()) == {"namespace": "ksirg-hollow"}
    cfg = json.loads((home / ".claude.json").read_text())
    assert cfg["mcpServers"]["cogito-mem"] == {"type": "stdio", "command": str(launcher), "args": ["mcp"], "env": {}}
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    assert data["hooks"]["Stop"][0] == their_hook
    assert len(data["hooks"]["Stop"]) == 2 and len(data["hooks"]["SessionEnd"]) == 1
    ours = data["hooks"]["Stop"][1]["hooks"][0]
    assert ours["command"] == f"{launcher} capture claude-code"
    assert data["hooks"]["UserPromptSubmit"] == [
        {"hooks": [{"type": "command", "command": f"{launcher} recall claude-code", "timeout": 5}]}
    ]
    assert data["hooks"]["SessionStart"] == [
        {"matcher": "startup|resume", "hooks": [{"type": "command", "command": f"{launcher} recall claude-code", "timeout": 10}]}
    ]
    assert (settings.parent / "settings.json.cogito-mem.bak").exists()

    uninstall("claude-code", root, say=lambda s: None)
    data = json.loads(settings.read_text())
    assert data == {"model": "opus", "hooks": {"Stop": [their_hook]}}
    assert "cogito-mem" not in json.loads((home / ".claude.json").read_text()).get("mcpServers", {})
    assert (root / "memory" / "ksirg-hollow" / "log.sqlite3").exists()  # the memory is kept


@pytest.mark.skipif(shutil.which("claude") is None, reason="the claude CLI is not installed")
def test_install_claude_code_without_recall(isolated_env, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_NO_CLAUDE_CLI", "1")
    home = isolated_env
    root = home / ".cogito-mem"
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    their_start = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo hello"}]}
    settings.write_text(json.dumps({"hooks": {"SessionStart": [their_start]}}))

    run_install("claude-code", root)
    assert len(json.loads(settings.read_text())["hooks"]["SessionStart"]) == 2
    lines = run_install("claude-code", root, recall=False)  # turns recall off again
    assert any("recall hooks left out" in line for line in lines)
    hooks = json.loads(settings.read_text())["hooks"]
    assert sorted(hooks) == ["SessionEnd", "SessionStart", "Stop"]
    assert hooks["SessionStart"] == [their_start]
    assert "capture claude-code" in hooks["Stop"][0]["hooks"][0]["command"]

    uninstall("claude-code", root, say=lambda s: None)
    assert json.loads(settings.read_text()) == {"hooks": {"SessionStart": [their_start]}}


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


def test_install_without_a_client_finds_the_installed_ones(isolated_env, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_NO_CLAUDE_CLI", "1")
    monkeypatch.setenv("PATH", str(isolated_env / "no-bin"))  # no claude or codex binaries
    home = isolated_env
    (home / ".codex").mkdir()
    (home / ".claude").mkdir()
    lines: list[str] = []
    assert install(None, home / ".cogito-mem", say=lines.append, download=False, start=False) == 0
    assert lines[0] == "Installing cogito-mem for claude-code, codex, claude-desktop"
    assert "cogito-mem" in json.loads((home / ".claude.json").read_text())["mcpServers"]
    assert "[mcp_servers.cogito-mem]" in (home / ".codex" / "config.toml").read_text()
    assert "cogito-mem" in json.loads((home / "claude_desktop_config.json").read_text())["mcpServers"]


def test_install_with_url_points_the_launcher_at_that_service(isolated_env):
    root = isolated_env / ".cogito-mem"
    lines: list[str] = []
    assert install("claude-desktop", root, say=lines.append, start=False, url="http://127.0.0.1:7999") == 0
    text = (root / "bin" / "cogito-mem").read_text()
    assert "COGITO_MEM_URL='http://127.0.0.1:7999'" in text
    assert any("using the service at http://127.0.0.1:7999" in line for line in lines)
    assert not (root / "models").exists()  # nothing downloaded: the service has its own model


def test_setup_downloads_the_model(isolated_env, monkeypatch, tmp_path):
    from cogito_mem.install import setup

    src = tmp_path / "m.gguf"
    src.write_bytes(b"GGUF")
    monkeypatch.setenv("COGITO_MEM_MODEL_URL", src.as_uri())
    monkeypatch.delenv("COGITO_MEM_NO_DOWNLOAD", raising=False)
    monkeypatch.delenv("COGITO_MEM_MODEL", raising=False)
    root = isolated_env / ".cogito-mem"
    lines: list[str] = []
    assert setup(root, say=lines.append, model_only=True) == 0
    assert (root / "models" / "embeddinggemma-2-Q8_0.gguf").read_bytes() == b"GGUF"


def test_doctor_reports_problems_and_fixes(isolated_env, monkeypatch):
    from cogito_mem.doctor import doctor

    monkeypatch.setenv("COGITO_MEM_URL", "http://127.0.0.1:9")  # nothing listens there
    lines: list[str] = []
    assert doctor(isolated_env / ".cogito-mem", say=lines.append) == 1
    text = "\n".join(lines)
    assert "[FAIL] memory folder" in text and "fix: run `cogito-mem install`" in text
    assert "[FAIL] service at http://127.0.0.1:9" in text
    assert f"[ok  ] memory: ksirg-hollow ({isolated_env / '.cogito-mem' / 'memory' / 'ksirg-hollow'})" in text
    assert "problem(s) found" in lines[-1]


def test_claude_code_plugin_files_are_consistent():
    repo = Path(__file__).resolve().parents[1]
    # The plugin is its own folder: all that people who install it get, and all that the directory scans.
    folder = repo / "plugin"
    plugin = json.loads((folder / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((repo / ".claude-plugin" / "marketplace.json").read_text())
    assert plugin["name"] == "cogito-mem" == market["plugins"][0]["name"]
    assert market["plugins"][0]["source"] == "./plugin"
    assert not (repo / ".claude-plugin" / "plugin.json").exists() and not (repo / "hooks").exists()
    # The MCP server is declared in plugin.json: a root .mcp.json would also load as a project
    # config when the repository is opened in Claude Code, where ${CLAUDE_PLUGIN_ROOT} is unset.
    assert not (repo / ".mcp.json").exists()
    shipped = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                     if p.is_file() and ".venv" not in p.parts and "__pycache__" not in p.parts)
    assert shipped == [".claude-plugin/plugin.json", "LICENSE", "README.md", "cogi-card.png", "hooks/hooks.json",
                       "icon.png", "pyproject.toml", "uv.lock"]
    # Every command runs the released package at the version the plugin pins (shown in /mcp as
    # plugin:cogito-mem:cogi), in the plain `uvx <package>==<version>` form the directory's locked launch reads.
    from cogito_mem import __version__

    pin = f"cogito-mem=={plugin['version']}"
    assert tuple(map(int, plugin["version"].split("."))) <= tuple(map(int, __version__.split(".")))
    mcp = plugin["mcpServers"]["cogi"]
    assert [mcp["command"], *mcp["args"]] == ["uvx", pin, "mcp"]
    assert mcp["env"] == {"CLAUDE_PLUGIN_OPTION_MEMORY_NAME": "${user_config.memory_name}"}
    hooks = json.loads((folder / "hooks" / "hooks.json").read_text())["hooks"]
    for event in ("Stop", "SessionEnd"):
        assert hooks[event][0]["hooks"][0]["command"] == f"uvx {pin} capture claude-code"
    for event in ("UserPromptSubmit", "SessionStart"):
        assert hooks[event][0]["hooks"][0]["command"] == f"uvx {pin} recall claude-code"
    assert hooks["SessionStart"][0]["matcher"] == "startup|resume"
    # uv.lock beside it records that release, from PyPI, and its dependencies with their hashes
    assert f'dependencies = ["{pin}"]' in (folder / "pyproject.toml").read_text()
    lock = (folder / "uv.lock").read_text()
    assert f'name = "cogito-mem"\nversion = "{plugin["version"]}"\nsource = {{ registry = "https://pypi.org/simple" }}' in lock
    assert 'name = "numpy"' in lock and "sha256:" in lock
    # the directory reads these listing fields; displayName must have no invisible characters
    assert plugin["displayName"].isprintable() and all(ord(c) < 0x2000 for c in plugin["displayName"])
    assert (folder / plugin["icon"]).is_file()
    for key in ("documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl", "homepage"):
        assert plugin[key].startswith("https://")
    assert market["plugins"][0]["category"] == "productivity"
    # the MCP Registry entry ships with the package's version, and the README carries its ownership line
    server = json.loads((repo / "server.json").read_text())
    assert server["version"] == server["packages"][0]["version"] == __version__
    readme = (repo / "README.md").read_text()
    assert f"<!-- mcp-name: {server['name']} -->" in readme
    # the README is also the PyPI page, where links relative to the repository go nowhere; only bundled images may be
    # relative, and the release points them at GitHub before building
    assert all(link.startswith(("https://", "site/assets/")) for link in readme.split("](")[1:])
    assert 'sed -i "s#](site/assets/#](https://' in (repo / ".github/workflows/release.yml").read_text()
    # the plugin's README is the listing: links on the web or to its own images, at least 40 words
    listing = (folder / "README.md").read_text()
    assert all(link.startswith("https://") or (folder / link.split(")")[0]).is_file() for link in listing.split("](")[1:])
    assert len(" ".join(listing.split("```")[::2]).split()) >= 40 and "uvx cogito-mem==" in listing
    # the directory keeps each line break, so a paragraph or list item is one line
    for text in (readme, listing):
        prose = text.split("```")[::2]
        assert not any(a and b and not b.startswith(("-", "|", "#", ">", "<", "!", "[")) and not b[0].isdigit()
                       for part in prose for a, b in zip(part.splitlines(), part.splitlines()[1:]))

def test_install_guides_use_pypi_not_a_piped_script():
    # the plugin directory flags a download piped into a shell anywhere in the plugin, docs included
    repo = Path(__file__).resolve().parents[1]
    for page in ("docs/install.md", "site/start.html"):
        assert "uv tool install cogito-mem" in (repo / page).read_text()
    piped = re.compile("|".join(rf"\|\s*{shell}\b" for shell in ("sh", "bash", "iex")))
    for path in [repo / "README.md", *repo.glob("docs/*.md"), *repo.glob("site/*.html")]:
        assert not piped.search(path.read_text()), path
