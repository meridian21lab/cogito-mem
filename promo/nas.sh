#!/usr/bin/env bash
# Keep promo video builds on the NAS. Git holds the sources of each video (scenes.json, make_video.py,
# publish.md); the NAS holds what costs money or time to make again: the rendered videos and covers,
# the ElevenLabs voice clips (audio/) and raw screen recordings (raw/). Stills are skipped: --stills
# remakes them in seconds.
#
# The NAS is mounted on the home server Odra at /nas/ml_data, not on the Mac, so everything goes
# through `ssh odra` (override with COGI_NAS_HOST / COGI_NAS_DIR).
#
#   bash promo/nas.sh push                      # every video folder -> NAS
#   bash promo/nas.sh push 01-claude-forgets    # one video
#   bash promo/nas.sh pull 01-claude-forgets    # NAS -> here, e.g. on a fresh checkout, so TTS is not paid twice
#   bash promo/nas.sh ls                        # what the NAS holds
#
# Additive: never deletes on either side; a newer render replaces the older file of the same name.
set -euo pipefail

HOST=${COGI_NAS_HOST:-odra}
NAS=${COGI_NAS_DIR:-/nas/ml_data/cogito-mem/promo/videos}
VIDEOS=$(cd "$(dirname "$0")" && pwd)/videos
cmd=${1:?usage: nas.sh push|pull|ls [video]}
only=${2:-}

ssh -o BatchMode=yes "$HOST" "mountpoint -q /nas/ml_data" ||
  { echo "The NAS is not mounted on $HOST at /nas/ml_data (or $HOST is unreachable)." >&2; exit 1; }

case "$cmd" in
  push)
    for dir in "$VIDEOS"/*/; do
      name=$(basename "$dir")
      [[ -n "$only" && "$name" != "$only" ]] && continue
      src=()
      for f in "$dir"*.mp4 "$dir"cover*.jpg "$dir"audio "$dir"raw; do
        [[ -e "$f" ]] && src+=("$f")
      done
      if [[ ${#src[@]} -eq 0 ]]; then
        echo "$name: nothing built yet"
        continue
      fi
      ssh -o BatchMode=yes "$HOST" "mkdir -p '$NAS/$name'"
      rsync -rlt "${src[@]}" "$HOST:$NAS/$name/"
      echo "$name -> $HOST:$NAS/$name/"
    done
    ;;
  pull)
    [[ -n "$only" ]] || { echo "pull needs a video name, e.g. 01-claude-forgets" >&2; exit 1; }
    mkdir -p "$VIDEOS/$only"
    rsync -rlt "$HOST:$NAS/$only/" "$VIDEOS/$only/"
    echo "$HOST:$NAS/$only/ -> $VIDEOS/$only/"
    ;;
  ls)
    ssh -o BatchMode=yes "$HOST" "cd '$NAS' 2>/dev/null && du -sh -- */ || echo 'nothing on the NAS yet ($NAS)'"
    ;;
  *)
    echo "usage: nas.sh push|pull|ls [video]" >&2
    exit 1
    ;;
esac
