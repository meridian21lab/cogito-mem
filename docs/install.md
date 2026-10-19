# Installing cogito-mem

cogito-mem runs on your own machine: macOS or Linux (Windows is experimental), about 1 GB of disk, no GPU
needed. Pick **one** of the four ways below; they all give the same memory in `~/.cogito-mem`.

| Way | Best for | Needs |
|---|---|---|
| [A. One line](#a-one-line-recommended) | Most people | `curl` |
| [B. Claude Code plugin](#b-claude-code-plugin) | Claude Code only, from inside Claude Code | `uv` (or Python 3.10+ with numpy) |
| [C. Docker](#c-docker) | Servers, or keeping everything in a container | Docker |
| [D. By hand](#d-by-hand) | Python developers | Python 3.10+ |

## A. One line (recommended)

```sh
curl -fsSL https://raw.githubusercontent.com/meridian21lab/cogito-mem/main/install.sh | sh
```

On Windows (experimental):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/meridian21lab/cogito-mem/main/install.ps1 | iex"
```

It installs [uv](https://docs.astral.sh/uv/) if you don't have it (uv brings its own Python), installs cogito-mem
as a uv tool, and then runs `cogito-mem install`, which:

1. creates `~/.cogito-mem` with one memory, named `<username>-hollow` (e.g. `ksirg-hollow`); pass `--name` to
   choose another (`curl … | sh -s -- --name work`);
2. gets llama.cpp's `llama-server` (the one on your `PATH`, e.g. `brew install llama.cpp`, or the official
   prebuilt release) and the EmbeddingGemma 2 model (310 MB);
3. connects **every chat client it finds**: Claude Code (MCP server + capture and recall hooks), Codex (MCP server + capture
   after each turn), Claude Desktop (MCP server);
4. starts the local service and checks it answers.

To connect only some clients: `curl … | sh -s -- claude-code codex`. Then **restart your chat client**.

## B. Claude Code plugin

Inside Claude Code:

```
/plugin marketplace add meridian21lab/cogito-mem
/plugin install cogito-mem@cogito-mem
```

Or in one step: `/plugin install cogito-mem --marketplace meridian21lab/cogito-mem`.

When you enable it, the plugin asks you to **name your memory**; leave it empty for `<username>-hollow`.
The plugin registers the MCP server and the capture and recall hooks. It runs cogito-mem through `uv` (the first start takes a
few seconds while uv builds its environment), or through an installed `cogito-mem`, or a `python3` that has numpy.
On its first start the service downloads llama.cpp (unless one is on your `PATH`) and the model (310 MB) into
`~/.cogito-mem`; until they are ready, the memory searches by keyword.

Don't combine the plugin with way A for Claude Code: you would get the tools twice (capture would still store each
message once).

## C. Docker

```sh
docker run -d --name cogito-mem --restart unless-stopped \
  -p 127.0.0.1:7327:7327 -v cogito-mem:/data ghcr.io/meridian21lab/cogito-mem:latest
```

or, from a checkout, `docker compose up -d`. The image holds the service and llama.cpp, for amd64 and arm64
(Graviton, Ampere, Apple Silicon); the model is downloaded into the `/data` volume on first start (build with
`--build-arg BAKE_MODEL=1` to put it in the image). Docker on a Mac runs on the CPU only, so on a Mac way A is
faster. Then connect your clients by URL:

```sh
claude mcp add --transport http --scope user cogito-mem http://127.0.0.1:7327/mcp      # Claude Code
```

```toml
# ~/.codex/config.toml (Codex), through a local bridge:
[mcp_servers.cogito-mem]
command = "cogito-mem"
args = ["mcp"]
env = { COGITO_MEM_URL = "http://127.0.0.1:7327" }
```

Automatic capture reads chat files on your machine, so it needs the host CLI: with cogito-mem installed on the
host (way A or D), `cogito-mem install --url http://127.0.0.1:7327` points the MCP bridge and the capture hooks at
the container instead of a local service.

Keep the port bound to `127.0.0.1`: the memory has no accounts, so anyone who can reach the port can read it.

## D. By hand

```sh
uv tool install git+https://github.com/meridian21lab/cogito-mem     # or: pipx install … / pip install …
cogito-mem install                                                  # every client found; or name them
```

## Check it

```sh
cogito-mem doctor
```

prints every part of the install (folder, llama.cpp, model, service, each client) and how to fix what is missing.
Then, in a chat: *"Remember that the beta goes to ten design partners first."* and, later, *"What did we decide
about the beta?"*. From a terminal: `cogito-mem query "beta design partners"`.

## Bring in past chats

```sh
cogito-mem capture claude-code --all                  # every earlier Claude Code session
cogito-mem capture codex --all                        # every earlier Codex session
cogito-mem import claude  ~/Downloads/data-….zip      # claude.ai: Settings → Privacy → Export data
cogito-mem import chatgpt ~/Downloads/….zip           # ChatGPT: Settings → Data controls → Export
```

Importing the same file twice adds nothing.

## Upgrade, stop, remove

```sh
curl -fsSL https://raw.githubusercontent.com/meridian21lab/cogito-mem/main/install.sh | sh   # upgrade (way A)
cogito-mem stop                                  # stop the service (any request starts it again)
cogito-mem uninstall claude-code                 # or codex, claude-desktop; the memory is kept
rm -rf ~/.cogito-mem                             # erase the memory itself
```

To rename the memory, stop the service (`cogito-mem stop`), rename its folder in `~/.cogito-mem/memory/`, then
set the new name: `cogito-mem install --name <new>`, or in the plugin's options (`/plugin`). A memory from before
names (`memory/default`) is renamed to your memory's name by itself, once.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `doctor` says llama.cpp not found | `cogito-mem setup`, or `brew install llama.cpp` (macOS) |
| The model can't be downloaded (offline, firewall) | Put any copy of `embeddinggemma-2-Q8_0.gguf` in `~/.cogito-mem/models/`, or set `COGITO_MEM_MODEL=/path/to/file.gguf` |
| Port 7327 is taken | `export COGITO_MEM_PORT=7400` before `cogito-mem install` |
| Search finds only exact words | The model isn't loaded: run `cogito-mem doctor`; logs are in `~/.cogito-mem/run/` |
| Run on CPU only | `COGITO_MEM_GPU_LAYERS=0` |
| Behind a TLS-inspecting proxy | Set `SSL_CERT_FILE` to your CA bundle; for Docker builds pass `--secret id=extra_ca,src=ca.pem` |

Everything else has a working default; the full list of settings is in the [README](../README.md#settings).
