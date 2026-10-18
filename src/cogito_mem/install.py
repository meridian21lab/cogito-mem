"""``cogito-mem install <client>`` and ``cogito-mem uninstall <client>`` (requirements §3.5).

Install, in one command and with nothing to configure:

1. creates the memory folder (``~/.cogito-mem``) with the namespace ``default``;
2. writes a launcher, ``~/.cogito-mem/bin/cogito-mem``, that every client calls;
3. gets llama.cpp's ``llama-server`` (if it is not on the PATH) and the
   EmbeddingGemma 2 GGUF;
4. registers the MCP server with the client and turns on automatic capture where
   the client has hooks (Claude Code hooks, Codex ``notify``);
5. starts the local service and checks that it answers a query.

Uninstall removes only what install added; the memory folder is kept.
Every config file is backed up once (``*.cogito-mem.bak``) before it is first changed.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

CLIENTS = ("claude-code", "codex", "claude-desktop")
SERVER_NAME = "cogito-mem"
_BEGIN = "# >>> cogito-mem >>>"
_END = "# <<< cogito-mem <<<"
_NOTIFY_BEGIN = "# >>> cogito-mem notify >>>"
_NOTIFY_END = "# <<< cogito-mem notify <<<"

Say = Callable[[str], None]


# --------------------------------------------------------------------------- helpers


def launcher_path(root: Path) -> Path:
    return root / "bin" / ("cogito-mem.cmd" if os.name == "nt" else "cogito-mem")


def write_launcher(root: Path) -> Path:
    path = launcher_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path.write_text(f'@echo off\r\nset "COGITO_MEM_HOME={root}"\r\n"{sys.executable}" -m cogito_mem %*\r\n')
    else:
        path.write_text(
            "#!/bin/sh\n"
            "# Written by `cogito-mem install`; run it again to update this file.\n"
            f"COGITO_MEM_HOME='{root}'\nexport COGITO_MEM_HOME\n"
            f"exec '{sys.executable}' -m cogito_mem \"$@\"\n"
        )
        path.chmod(0o755)
    return path


def _backup(path: Path) -> None:
    backup = path.with_name(path.name + ".cogito-mem.bak")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)


def _read_json(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _is_ours(command: object) -> bool:
    return isinstance(command, str) and "cogito-mem" in command and "capture" in command


# --------------------------------------------------------------------------- Claude Code


def claude_dir() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def claude_json() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(env).expanduser() if env else Path.home()) / ".claude.json"


def _claude_cli() -> str | None:
    if os.environ.get("COGITO_MEM_NO_CLAUDE_CLI"):
        return None
    return shutil.which("claude")


def _mcp_entry(launcher: Path) -> dict:
    return {"type": "stdio", "command": str(launcher), "args": ["mcp"], "env": {}}


def install_claude_code(launcher: Path, say: Say) -> None:
    cli = _claude_cli()
    registered = False
    if cli:
        subprocess.run([cli, "mcp", "remove", "--scope", "user", SERVER_NAME], capture_output=True, timeout=60)
        res = subprocess.run(
            [cli, "mcp", "add", "--scope", "user", SERVER_NAME, "--", str(launcher), "mcp"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        registered = res.returncode == 0
        if not registered:
            say(f"  `claude mcp add` failed ({res.stderr.strip() or res.stdout.strip()}); editing the config instead")
    if not registered:
        path = claude_json()
        data = _read_json(path)
        data.setdefault("mcpServers", {})[SERVER_NAME] = _mcp_entry(launcher)
        _write_json(path, data)
    say("  MCP server registered for Claude Code (user scope)")

    settings_path = claude_dir() / "settings.json"
    settings = _read_json(settings_path)
    hooks = settings.setdefault("hooks", {})
    command = f"'{launcher}' capture claude-code" if " " in str(launcher) else f"{launcher} capture claude-code"
    for event in ("Stop", "SessionEnd"):
        groups = [g for g in hooks.get(event, []) if not _group_is_ours(g)]
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 30}]})
        hooks[event] = groups
    _write_json(settings_path, settings)
    say(f"  capture hooks (Stop, SessionEnd) added to {settings_path}")


def _group_is_ours(group: object) -> bool:
    if not isinstance(group, dict):
        return False
    hooks = group.get("hooks") or []
    return bool(hooks) and all(isinstance(h, dict) and _is_ours(h.get("command")) for h in hooks)


def uninstall_claude_code(say: Say) -> None:
    cli = _claude_cli()
    if cli:
        subprocess.run([cli, "mcp", "remove", "--scope", "user", SERVER_NAME], capture_output=True, timeout=60)
    path = claude_json()
    if path.exists():
        data = _read_json(path)
        if SERVER_NAME in data.get("mcpServers", {}):
            del data["mcpServers"][SERVER_NAME]
            _write_json(path, data)
    say("  MCP server removed from Claude Code")
    settings_path = claude_dir() / "settings.json"
    if settings_path.exists():
        settings = _read_json(settings_path)
        hooks = settings.get("hooks", {})
        for event in list(hooks):
            kept = [g for g in hooks[event] if not _group_is_ours(g)]
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
        if not hooks:
            settings.pop("hooks", None)
        _write_json(settings_path, settings)
        say(f"  capture hooks removed from {settings_path}")


# --------------------------------------------------------------------------- Codex


def codex_config() -> Path:
    from .capture.codex import codex_home

    return codex_home() / "config.toml"


def _strip_block(text: str, begin: str, end: str) -> str:
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if line.strip() == begin:
            skipping = True
            continue
        if line.strip() == end and skipping:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "".join(out)


def _tidy(text: str) -> str:
    """The text with one blank line after it, ready for a block to be added."""
    return text.rstrip("\n") + "\n\n" if text.strip() else ""


def _toml_str(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid TOML basic string


def _has_top_level_key(text: str, key: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            return False
        if stripped.split("=", 1)[0].strip() == key and "=" in stripped:
            return True
    return False


def install_codex(launcher: Path, say: Say) -> None:
    path = codex_config()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    text = _tidy(_strip_block(_strip_block(text, _BEGIN, _END), _NOTIFY_BEGIN, _NOTIFY_END))
    if "[mcp_servers.cogito-mem]" in text or '[mcp_servers."cogito-mem"]' in text:
        say(f"  {path} already defines mcp_servers.cogito-mem; left as is")
    else:
        text += (
            f"{_BEGIN}\n[mcp_servers.cogito-mem]\ncommand = {_toml_str(str(launcher))}\n"
            f'args = ["mcp"]\n{_END}\n'
        )
        say("  MCP server registered for Codex")
    if _has_top_level_key(text, "notify"):
        say(f"  {path} already sets notify; capture after each turn is off (run `cogito-mem capture codex` by hand)")
    else:
        notify = f"notify = [{_toml_str(str(launcher))}, \"capture\", \"codex\"]"
        text = f"{_NOTIFY_BEGIN}\n{notify}\n{_NOTIFY_END}\n" + text
        say("  capture after each turn turned on (Codex notify)")
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    path.write_text(text, encoding="utf-8")


def uninstall_codex(say: Say) -> None:
    path = codex_config()
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    new = _strip_block(_strip_block(text, _BEGIN, _END), _NOTIFY_BEGIN, _NOTIFY_END)
    if new != text:
        _backup(path)
        new = new.rstrip("\n") + "\n" if new.strip() else ""
        path.write_text(new, encoding="utf-8")
    say("  MCP server and notify removed from Codex")


# --------------------------------------------------------------------------- Claude Desktop


def claude_desktop_config() -> Path:
    env = os.environ.get("COGITO_MEM_CLAUDE_DESKTOP_CONFIG")
    if env:
        return Path(env).expanduser()
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def install_claude_desktop(launcher: Path, say: Say) -> None:
    path = claude_desktop_config()
    data = _read_json(path)
    data.setdefault("mcpServers", {})[SERVER_NAME] = {"command": str(launcher), "args": ["mcp"]}
    _write_json(path, data)
    say(f"  MCP server registered in {path} (restart Claude Desktop to load it)")


def uninstall_claude_desktop(say: Say) -> None:
    path = claude_desktop_config()
    if path.exists():
        data = _read_json(path)
        if SERVER_NAME in data.get("mcpServers", {}):
            del data["mcpServers"][SERVER_NAME]
            _write_json(path, data)
    say("  MCP server removed from Claude Desktop")


# --------------------------------------------------------------------------- entry points


def ensure_runtime(root: Path, say: Say, download: bool = True) -> bool:
    from . import runtime

    ok = True
    binary = runtime.find_llama_server(root)
    if binary is None and os.environ.get("COGITO_MEM_LLAMA_SERVER", "").startswith("http"):
        say(f"  using the llama-server at {os.environ['COGITO_MEM_LLAMA_SERVER']}")
    elif binary is None and download:
        try:
            binary = runtime.install_llama_server(root)
            say(f"  llama.cpp installed: {binary}")
        except Exception as exc:
            ok = False
            say(f"  could not get llama.cpp ({exc}); install it (e.g. `brew install llama.cpp`)")
    elif binary is None:
        ok = False
        say("  llama-server not found; install llama.cpp (e.g. `brew install llama.cpp`)")
    else:
        say(f"  llama.cpp: {binary}")
    try:
        model = runtime.ensure_model(root, allow_download=download)
        say(f"  embedding model: {model}")
    except Exception as exc:
        ok = False
        say(f"  could not get the embedding model ({exc})")
    if not ok:
        say("  until then the memory searches by keyword only")
    return ok


def install(client: str, root: Path, say: Say = print, download: bool = True, start: bool = True) -> int:
    if client not in CLIENTS:
        say(f"unknown client {client!r}; choose one of: {', '.join(CLIENTS)}")
        return 2
    from .memory import Memory

    say(f"Installing cogito-mem for {client}")
    with Memory(root, embedder=None) as mem:
        mem.namespace("default")
    say(f"  memory folder: {root} (namespace 'default')")
    launcher = write_launcher(root)
    ensure_runtime(root, say, download)
    {"claude-code": install_claude_code, "codex": install_codex, "claude-desktop": install_claude_desktop}[client](
        launcher, say
    )
    if start:
        from .client import Client

        try:
            client_ = Client(root=root)
            if client_.stop_server():  # restart, so a new model or llama.cpp is picked up
                say("  stopped the running service to restart it")
            client_.query("cogito-mem install check", max_tokens=1)
            info = client_.status() or {}
            state = (info.get("embedder") or {}).get("state", "unknown")
            say(f"  service running at {client_.url} (embedding model: {state})")
        except Exception as exc:
            say(f"  the service did not answer ({exc}); see {root / 'run' / 'server.log'}")
            return 1
    say("Done. Ask your assistant: \"Do you remember ...?\"")
    return 0


def uninstall(client: str, root: Path, say: Say = print) -> int:
    if client not in CLIENTS:
        say(f"unknown client {client!r}; choose one of: {', '.join(CLIENTS)}")
        return 2
    say(f"Removing cogito-mem from {client}")
    {"claude-code": uninstall_claude_code, "codex": uninstall_codex, "claude-desktop": uninstall_claude_desktop}[
        client
    ](say)
    say(f"The memory itself is kept in {root}; delete that folder to erase it.")
    return 0
