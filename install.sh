#!/bin/sh
# Install cogito-mem and connect it to every chat client found (Claude Code, Codex, Claude Desktop).
#
#   curl -fsSL https://raw.githubusercontent.com/meridian21lab/cogito-mem/main/install.sh | sh
#   curl -fsSL .../install.sh | sh -s -- claude-code        # only one client
#
# Needs only curl: it installs uv (https://docs.astral.sh/uv/) if missing, uv brings Python,
# and cogito-mem lands in uv's tool directory, outside any project. Re-run it to upgrade.
# COGITO_MEM_SOURCE overrides where cogito-mem is installed from (a path, a git URL, a version).
set -eu

SOURCE="${COGITO_MEM_SOURCE:-git+https://github.com/meridian21lab/cogito-mem}"

say() { printf 'cogito-mem: %s\n' "$*"; }

if ! command -v uv >/dev/null 2>&1; then
  say "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi

say "installing cogito-mem from $SOURCE"
uv tool install --force --quiet --python 3.12 "$SOURCE"
PATH="$(uv tool dir --bin):$PATH"
export PATH

cogito-mem install "$@"
say "done. Check the install any time with: cogito-mem doctor"
