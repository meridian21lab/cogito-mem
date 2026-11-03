# Install Cogi: steps for an AI agent

You are installing Cogi (cogito-mem) for the person you work with. Cogi is a local memory for Claude Code and Codex:
it keeps their messages on this computer and sends nothing anywhere. Follow the steps in order. Show each command
before you run it. If a step fails twice, stop and tell the person what you saw.

Do not use `sudo`, do not edit their settings files by hand, and never delete `~/.cogito-mem` (it holds their memories).

## 1. Check the computer

1. Find the operating system. macOS and Linux are supported. Windows is experimental: say so, and go on only if the
   person agrees.
2. Find the apps: run `claude --version` (Claude Code) and `codex --version` (Codex). Install Cogi for each one found.
   If neither is found, stop: Cogi needs one of them.
3. Claude Code must be 2.1.292 or newer. If it is older, ask the person to update it (`claude update`) and stop.
4. Check for about 1 GB of free disk space: the embedding model alone is 310 MB.
5. Run `uv --version`. If it works, skip step 2.

## 2. Install uv

uv runs Cogi and brings its own Python.

- macOS, with Homebrew: `brew install uv`
- Windows: `winget install --id=astral-sh.uv -e`
- Anything else: follow https://docs.astral.sh/uv/getting-started/installation/ and ask the person before you run
  its installer.

Then check `uv --version` again. If it is not found, the terminal needs a restart: ask the person to open a new one,
or use the full path the installer printed.

## 3. Install Cogi

**Claude Code**: the plugin.

```
claude plugin install cogito-mem --marketplace meridian21lab/cogito-mem
```

Expect `Successfully installed plugin: cogito-mem@cogito-mem (scope: user)`. "Already installed" is fine too.

**Codex** (and Claude Desktop, if the person wants it there too):

```
uv tool install cogito-mem
cogito-mem install codex
```

Add `claude-desktop` after `codex` to include Claude Desktop. If `cogito-mem` is not found, run
`uv tool update-shell` and call it by its full path, in the folder `uv tool dir --bin` prints. Do not run
`cogito-mem install` without naming the apps when the plugin is installed: the plugin already covers Claude Code,
and installing both would save every message twice.

## 4. Get it ready

Download llama.cpp and the embedding model now, so the first search is fast (about a minute):

```
uvx cogito-mem setup
```

Then check:

- Claude Code: `claude plugin list` shows `cogito-mem@cogito-mem` and `✔ enabled`.
- Codex: `cogito-mem doctor` ends with `all good`.

## 5. Tell the person

Say what you installed and that they need to **restart Claude Code** (or Codex) for Cogi to load. After the restart,
`/mcp` in Claude Code shows `plugin:cogito-mem:cogi ✔ 3 tools`. Suggest this test:

1. Say: *Let's call the staging server "acorn".*
2. Type `/clear`.
3. Ask: *What did we call the staging server?* Claude answers "acorn".

Their memory is called `<username>-hollow`. Cogi saves from now on. Ask whether they also want their earlier
Claude Code sessions added, and warn them that old sessions may hold secrets Cogi's redaction misses. Only if they
say yes:

```
uv tool install cogito-mem
cogito-mem capture claude-code --all
```

More: https://meridian21lab.github.io/cogito-mem/start.html · What gets installed:
https://meridian21lab.github.io/cogito-mem/safety.html
