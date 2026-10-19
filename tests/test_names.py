"""The memory's name: <username>-hollow, the config file, and the rename from `default`."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import append

from cogito_mem import Memory, names
from cogito_mem.api import NAMESPACE_RE

SRC = str(Path(__file__).resolve().parents[1] / "src")
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(isolated_env, monkeypatch) -> Path:
    """The memory folder of a clean machine whose user is ksirg; no service runs on its port."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        monkeypatch.setenv("COGITO_MEM_PORT", str(s.getsockname()[1]))
    return isolated_env / ".cogito-mem"


def saved(root: Path) -> dict:
    return json.loads((root / "config.json").read_text())


# --------------------------------------------------------------------------- the name


@pytest.mark.parametrize(
    "user, name",
    [
        ("ksirg", "ksirg-hollow"),
        ("Krzysztof.Sopyla", "krzysztof.sopyla-hollow"),
        ("Jan Kowalski", "jan-kowalski-hollow"),
        ("CORP\\jan", "corp-jan-hollow"),
        ("łukasz", "ukasz-hollow"),
        ("_admin_", "admin-hollow"),
        ("", "my-hollow"),
        ("ąę", "my-hollow"),
        ("x" * 100, "x" * 57 + "-hollow"),
    ],
)
def test_hollow_is_the_username_made_valid(user, name):
    assert names.hollow(user) == name
    assert NAMESPACE_RE.match(name)


def test_resolution_order(home, monkeypatch):
    assert names.default_namespace(home) == "ksirg-hollow"  # the username
    assert saved(home) == {"namespace": "ksirg-hollow"}
    (home / "config.json").write_text(json.dumps({"namespace": "work", "other": 1}))
    assert names.default_namespace(home) == "work"  # the config file
    monkeypatch.setenv("COGITO_MEM_NAMESPACE", "  ")
    assert names.default_namespace(home) == "work"  # empty counts as unset
    monkeypatch.setenv("COGITO_MEM_NAMESPACE", "${user_config.memory_name}")
    assert names.default_namespace(home) == "work"  # a placeholder a client left in
    monkeypatch.setenv("COGITO_MEM_NAMESPACE", "team-hollow")
    assert names.default_namespace(home) == "team-hollow"  # the variable wins, and is saved for the others
    assert saved(home) == {"namespace": "team-hollow", "other": 1}
    monkeypatch.delenv("COGITO_MEM_NAMESPACE")
    assert names.default_namespace(home) == "team-hollow"


def test_a_bad_name_is_a_clear_error(home, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_NAMESPACE", "my memory")
    with pytest.raises(names.InvalidName, match=r"NAMESPACE 'my memory' is not a valid memory name: use 1-64"):
        names.default_namespace(home)
    assert not (home / "config.json").exists()
    monkeypatch.delenv("COGITO_MEM_NAMESPACE")
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({"namespace": "-bad"}))
    with pytest.raises(names.InvalidName, match="config.json '-bad' is not a valid memory name"):
        names.default_namespace(home)
    (home / "config.json").write_text("{not json")
    with pytest.raises(names.InvalidName, match="fix it or delete it"):
        names.default_namespace(home)


def cogito(home: Path, *args: str, input: str | None = None, **env: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": SRC, **env}
    argv = [sys.executable, "-m", "cogito_mem", "--root", str(home), *args]
    return subprocess.run(argv, input=input, capture_output=True, text=True, env=env, timeout=60)


def test_the_cli_says_what_is_wrong_and_what_it_renamed(home):
    out = cogito(home, "status", COGITO_MEM_NAMESPACE="my memory")
    assert out.returncode == 1 and "is not a valid memory name: use 1-64 letters" in out.stderr
    with Memory(home, embedder="hash") as m:
        append(m, {"author": "user", "text": "old"})
    out = cogito(home, "status")  # nothing runs on the port
    assert "memory: ksirg-hollow" in out.stdout
    assert out.stderr.startswith("cogito-mem: renamed the memory ") and out.stderr.count("\n") == 1


def test_the_mcp_server_answers_a_bad_name_with_the_rule(home):
    query = {"name": "memory_query", "arguments": {"text": "x"}}
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": query},
    ]
    out = cogito(home, "mcp", input="\n".join(json.dumps(r) for r in requests) + "\n", COGITO_MEM_NAMESPACE="my memory")
    assert out.returncode == 0, out.stderr
    reply = json.loads(out.stdout.splitlines()[1])["result"]
    assert reply["isError"] and "not a valid memory name: use 1-64" in reply["content"][0]["text"]


def test_a_request_without_namespace_goes_to_the_saved_name(tmp_path):
    root = tmp_path / "home"
    with Memory(root, embedder="hash") as m:
        m.append([{"author": "user", "text": "before any name"}])
        assert m.namespaces() == ["default"]  # nothing saved: the API's own default
        (root / "config.json").write_text(json.dumps({"namespace": "ksirg-hollow"}))
        m.append([{"author": "user", "text": "after naming"}])
        assert m.query("naming")["items"][0]["text"] == "after naming"
        assert m.namespace("ksirg-hollow").stats()["messages"] == 1


# --------------------------------------------------------------------------- the rename from `default`


def test_default_is_renamed_to_the_hollow_once(home, caplog):
    with Memory(home, embedder="hash") as m:
        append(m, {"author": "user", "text": "The beta goes to ten design partners."})
    caplog.set_level(logging.INFO, logger="cogito_mem.names")
    assert names.default_namespace(home) == "ksirg-hollow"
    assert not (home / "memory" / "default").exists()
    assert [r.levelname for r in caplog.records] == ["INFO"] and "renamed the memory" in caplog.text
    with Memory(home, embedder="hash") as m:
        assert m.query("design partners", namespace="ksirg-hollow")["items"][0]["text"].startswith("The beta")
        append(m, {"author": "script", "text": "a raw API caller later writes to default"})
    names.default_namespace(home)
    assert (home / "memory" / "default").exists()  # only the first name brings `default` along


def test_both_kept_when_both_exist(home, caplog):
    with Memory(home, embedder="hash") as m:
        append(m, {"author": "user", "text": "old"})
        append(m, {"author": "user", "text": "new"}, namespace="ksirg-hollow")
    assert names.default_namespace(home) == "ksirg-hollow"
    assert (home / "memory" / "default" / "log.sqlite3").exists()
    assert (home / "memory" / "ksirg-hollow" / "log.sqlite3").exists()
    assert "both" in caplog.text and caplog.records[-1].levelname == "WARNING"


def test_no_rename_when_the_name_is_default(home, monkeypatch):
    with Memory(home, embedder="hash") as m:
        append(m, {"author": "user", "text": "old"})
    monkeypatch.setenv("COGITO_MEM_NAMESPACE", "default")
    assert names.default_namespace(home) == "default"
    assert (home / "memory" / "default" / "log.sqlite3").exists()
    assert sorted(p.name for p in (home / "memory").iterdir()) == ["default"]


def test_a_running_service_is_stopped_before_the_rename(home, monkeypatch):
    from cogito_mem.client import Client

    with Memory(home, embedder="hash") as m:
        append(m, {"author": "user", "text": "old"})
    stopped = []
    monkeypatch.setattr(Client, "status", lambda self: {"pid": 999999, "root": str(home)})
    monkeypatch.setattr(Client, "stop_server", lambda self: stopped.append((home / "memory" / "default").exists()))
    assert names.default_namespace(home) == "ksirg-hollow"
    assert stopped == [True]  # stopped while `default` was still there
    assert (home / "memory" / "ksirg-hollow" / "log.sqlite3").exists()


def test_the_service_renames_only_to_a_chosen_name(home, monkeypatch):
    from cogito_mem.cli import _migrate_before_serving

    with Memory(home, embedder="hash") as m:
        append(m, {"author": "user", "text": "old"})
    _migrate_before_serving(home)  # no variable, no config: the service never guesses
    assert (home / "memory" / "default").exists() and not (home / "config.json").exists()
    monkeypatch.setenv("COGITO_MEM_NAMESPACE", "team-hollow")  # e.g. `docker run -e`
    _migrate_before_serving(home)
    assert (home / "memory" / "team-hollow" / "log.sqlite3").exists() and saved(home) == {"namespace": "team-hollow"}


# --------------------------------------------------------------------------- install and the plugin


def test_install_names_the_memory(home):
    from cogito_mem.install import install

    lines: list[str] = []
    assert install([], home, say=lines.append, download=False, start=False) == 0
    assert f"  memory: ksirg-hollow ({home / 'memory' / 'ksirg-hollow'})" in lines
    assert any("cogito-mem install --name <name>" in line for line in lines)
    assert install([], home, say=lines.append, download=False, start=False, name="work") == 0
    assert saved(home) == {"namespace": "work"} and (home / "memory" / "work" / "log.sqlite3").exists()
    lines.clear()
    assert install([], home, say=lines.append, download=False, start=False, name="my work") == 2
    assert "not a valid memory name" in lines[0]


def test_the_plugin_asks_for_the_name():
    plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
    option = plugin["userConfig"]["memory_name"]
    assert option["type"] == "string" and not option.get("required") and "default" not in option
    assert option["title"] == "Name your memory" and "-hollow" in option["description"]
    assert plugin["mcpServers"]["cogi"]["env"] == {"COGITO_MEM_NAMESPACE": "${user_config.memory_name}"}
    # Claude Code refuses ${user_config.*} in shell-form hook commands; the shim reads the env var instead
    assert "user_config" not in (REPO / "hooks" / "hooks.json").read_text()


@pytest.mark.parametrize(
    "option, preset, seen",
    [("work-hollow", None, "work-hollow"), ("", None, "unset"), (None, "keep", "keep"), ("", "keep", "keep")],
)
def test_the_plugin_shim_passes_the_name_on(tmp_path, option, preset, seen):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "cogito-mem"
    fake.write_text('#!/bin/sh\necho "${COGITO_MEM_NAMESPACE-unset}"\n')
    fake.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("COGITO_MEM_NAMESPACE", "CLAUDE_PLUGIN_OPTION_MEMORY_NAME")}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    if option is not None:
        env["CLAUDE_PLUGIN_OPTION_MEMORY_NAME"] = option
    if preset is not None:
        env["COGITO_MEM_NAMESPACE"] = preset
    out = subprocess.run(["sh", str(REPO / "scripts" / "cogito-mem-plugin"), "mcp"], capture_output=True, text=True,
                         env=env, timeout=30)  # fmt: skip
    assert out.returncode == 0 and out.stdout.strip() == seen
