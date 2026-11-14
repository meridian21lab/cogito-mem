#!/usr/bin/env bash
# Keep the films' paid and heavy files on the NAS. Git holds each film's sources (src/films/<film>/);
# the NAS holds what costs money or time to make again:
#   audio/    = public/films/<film>/ (ElevenLabs voice, sound effects, music, and their .json timings)
#   renders/  = out/<film>/ (the two cuts, covers, contact sheets)
#
# The NAS is mounted on the home server Odra at /nas/ml_data, not on the Mac, so everything goes
# through `ssh odra` (override with COGI_NAS_HOST / COGI_NAS_DIR).
#
#   bash promo/nas.sh push                      # every film -> NAS
#   bash promo/nas.sh push 01-claude-forgets    # one film
#   bash promo/nas.sh pull 01-claude-forgets    # NAS -> here, e.g. on a fresh checkout, so audio isn't paid twice
#   bash promo/nas.sh ls                        # what the NAS holds
#
# Additive: never deletes on either side; a newer file replaces the older one of the same name.
# The rejected Pillow-era episode 1 stays on the NAS under promo/videos/ as an archive.
set -euo pipefail

HOST=${COGI_NAS_HOST:-odra}
NAS=${COGI_NAS_DIR:-/nas/ml_data/cogito-mem/promo/films}
PROMO=$(cd "$(dirname "$0")" && pwd)
cmd=${1:?usage: nas.sh push|pull|ls [film]}
only=${2:-}

ssh -o BatchMode=yes "$HOST" "mountpoint -q /nas/ml_data" ||
  { echo "The NAS is not mounted on $HOST at /nas/ml_data (or $HOST is unreachable)." >&2; exit 1; }

case "$cmd" in
  push)
    for dir in "$PROMO"/public/films/*/; do
      [[ -d "$dir" ]] || continue
      film=$(basename "$dir")
      [[ -n "$only" && "$film" != "$only" ]] && continue
      ssh -o BatchMode=yes "$HOST" "mkdir -p '$NAS/$film/audio' '$NAS/$film/renders'"
      rsync -rlt "$dir" "$HOST:$NAS/$film/audio/"
      if [[ -d "$PROMO/out/$film" ]]; then
        rsync -rlt --exclude '*.raw.mp4' "$PROMO/out/$film/" "$HOST:$NAS/$film/renders/"
      fi
      echo "$film -> $HOST:$NAS/$film/"
    done
    ;;
  pull)
    [[ -n "$only" ]] || { echo "pull needs a film, e.g. 01-claude-forgets" >&2; exit 1; }
    mkdir -p "$PROMO/public/films/$only" "$PROMO/out/$only"
    rsync -rlt "$HOST:$NAS/$only/audio/" "$PROMO/public/films/$only/"
    rsync -rlt "$HOST:$NAS/$only/renders/" "$PROMO/out/$only/"
    echo "$HOST:$NAS/$only/ -> public/films/$only/ and out/$only/"
    ;;
  ls)
    ssh -o BatchMode=yes "$HOST" "cd '$NAS' 2>/dev/null && du -sh -- */ || echo 'nothing on the NAS yet ($NAS)'"
    ;;
  *)
    echo "usage: nas.sh push|pull|ls [film]" >&2
    exit 1
    ;;
esac
