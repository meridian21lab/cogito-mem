"""``cogito-mem doctor``: check every part of an install and say how to fix what is missing."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable

from . import __version__

Say = Callable[[str], None]


def _mark(ok: bool | None) -> str:
    return {True: "ok  ", False: "FAIL", None: "--  "}[ok]


def doctor(root: Path, url: str | None = None, say: Say = print) -> int:
    from . import runtime
    from .client import Client
    from .install import claude_desktop_config, claude_dir, claude_json, codex_config, launcher_path

    failures = 0

    def check(ok: bool | None, what: str, fix: str = "") -> None:
        nonlocal failures
        say(f"[{_mark(ok)}] {what}")
        if ok is False:
            failures += 1
            if fix:
                say(f"        fix: {fix}")

    say(f"cogito-mem {__version__} (Python {sys.version.split()[0]} at {sys.executable})")
    check(root.is_dir(), f"memory folder {root}", "run `cogito-mem install`")
    from .names import LEGACY, InvalidName, default_namespace

    try:
        name = default_namespace(root)
    except InvalidName as exc:
        check(False, f"memory name: {exc}", "set a valid name: `cogito-mem install --name <name>`")
        name = None
    else:
        check(True, f"memory: {name} ({root / 'memory' / name})")
        if name != LEGACY and (root / "memory" / LEGACY / "log.sqlite3").exists():
            check(None, f"a memory without a name is also kept in {root / 'memory' / LEGACY}")
    launcher = launcher_path(root)
    check(launcher.exists(), f"launcher {launcher}", "run `cogito-mem install`")

    url = url or os.environ.get("COGITO_MEM_URL")
    if not url:
        binary = runtime.find_llama_server(root)
        external = os.environ.get("COGITO_MEM_LLAMA_SERVER", "").startswith("http")
        check(bool(binary) or external, f"llama.cpp: {binary or os.environ.get('COGITO_MEM_LLAMA_SERVER') or 'not found'}",
              "run `cogito-mem setup`, or install llama.cpp (macOS: `brew install llama.cpp`)")  # fmt: skip
        model = runtime.model_path(root)
        check(model.exists(), f"embedding model: {model}", "run `cogito-mem setup`")

    client = Client(url=url, root=root)
    info = None
    try:
        client.query("cogito-mem doctor check", namespace=name, max_tokens=1)
        info = client.status()
    except Exception as exc:
        check(False, f"service at {client.url}: {exc}", f"see {root / 'run' / 'server.log'}")
    if info is not None:
        state = info.get("embedder", {}).get("state")
        check(True, f"service at {client.url} (pid {info.get('pid')})")
        check(state == "ready", f"embedding model in the service: {state}",
              "`cogito-mem stop`, fix the items above, then any request restarts it")  # fmt: skip
        for name, stats in sorted(info.get("namespaces", {}).items()):
            say(f"        namespace {name}: {stats['messages']} messages, {stats['items']} items, "
                f"{stats['vectors']} vectors, {stats['tokens']} tokens")  # fmt: skip

    def registered(path: Path, key: str = "mcpServers") -> bool | None:
        if not path.exists():
            return None
        try:
            return "cogito-mem" in json.loads(path.read_text()).get(key, {})
        except ValueError:
            return False

    cc = registered(claude_json())
    check(cc, "Claude Code: MCP server registered" if cc is not None else "Claude Code: not found",
          "run `cogito-mem install claude-code`")  # fmt: skip
    settings = claude_dir() / "settings.json"
    if cc is not None:
        hooked = settings.exists() and "capture claude-code" in settings.read_text()
        check(hooked, "Claude Code: capture hooks", "run `cogito-mem install claude-code`")
    cfg = codex_config()
    if cfg.exists():
        text = cfg.read_text()
        check("mcp_servers.cogito-mem" in text, "Codex: MCP server registered", "run `cogito-mem install codex`")
        check("capture" in text and "codex" in text, "Codex: capture after each turn (notify)")
    else:
        check(None, "Codex: not found")
    desk = registered(claude_desktop_config())
    check(desk, "Claude Desktop: MCP server registered" if desk is not None else "Claude Desktop: not found",
          "run `cogito-mem install claude-desktop`")  # fmt: skip
    say("all good" if failures == 0 else f"{failures} problem(s) found")
    return 0 if failures == 0 else 1
