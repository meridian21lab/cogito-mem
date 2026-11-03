#!/bin/bash
# Runs one rival's command with no network, no secrets and its own empty HOME.
#
#   run_sandboxed.sh <project> <command...>
#
# - env -i: nothing is inherited, so no API key, .env value or Claude variable reaches the rival.
# - HOME and TMPDIR are the project's own folders.
# - sandbox-exec (macOS): no network; the real ~/.claude, ~/.cogito-mem, the author's other dotfiles and
#   ~/devel can't be read; writes only inside rivals-m. A rival that reads ~/.claude by default gets an error.
# Run the install steps outside this wrapper: they are the only ones with network.
set -euo pipefail
BASE=${RIVALS_BASE:?set RIVALS_BASE to the rivals-m folder}
project=$1
shift
root="$BASE/$project"
mkdir -p "$root/home" "$root/tmp"
real_home=/Users/ksirg
profile="$root/sandbox.sb"
base_real=$(cd "$BASE" && pwd -P)
cat > "$profile" <<EOF
(version 1)
(allow default)
(deny network*)
(deny file-read* (subpath "$real_home/.claude") (literal "$real_home/.claude.json") (subpath "$real_home/.cogito-mem")
  (subpath "$real_home/devel") (subpath "$real_home/.ssh") (subpath "$real_home/.aws") (subpath "$real_home/.config")
  (subpath "$real_home/Library/Application Support/Claude") (subpath "$real_home/Documents") (subpath "$real_home/Desktop"))
(deny file-write*)
(allow file-write* (subpath "$base_real") (subpath "$BASE") (subpath "/dev"))
EOF
[ -d "$root/repo" ] && cd "$root/repo"
exec env -i \
  PATH="${RIVALS_PATH:-/usr/local/bin:/usr/bin:/bin}" \
  HOME="$root/home" TMPDIR="$root/tmp" LANG=en_US.UTF-8 \
  ANONYMIZED_TELEMETRY=False CHROMA_TELEMETRY_ENABLED=False DO_NOT_TRACK=1 GOTELEMETRY=off \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  ${RIVALS_ENV:-} \
  sandbox-exec -f "$profile" "$@"
