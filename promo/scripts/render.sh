#!/usr/bin/env bash
# Render both cuts of a film, master the audio, and make the covers.
#   bash scripts/render.sh 01-claude-forgets
# Writes out/<film>/{shorts,feed}.mp4 (H.264 + AAC 192k, -14 LUFS integrated, true peak <= -1 dBTP after
# a two-pass ffmpeg loudnorm) and out/<film>/cover-{shorts,feed}.jpg. Then run: npm run check -- <film>
set -euo pipefail
cd "$(dirname "$0")/.."
film=${1:?usage: render.sh <film id>, e.g. 01-claude-forgets}
slug=${film#[0-9][0-9]-}
out=out/$film
mkdir -p "$out"

for cut in shorts feed; do
  echo "== $cut"
  npx remotion render src/index.ts "$slug-$cut" "$out/$cut.raw.mp4" --log=error
  # pass 1: measure
  stats=$(ffmpeg -hide_banner -nostats -i "$out/$cut.raw.mp4" -af loudnorm=I=-14:TP=-2:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
  get() { python3 -c "import json,sys; print(json.loads(sys.argv[1])['$1'])" "$stats"; }
  # pass 2: apply linearly with the measured values
  ffmpeg -hide_banner -v error -y -i "$out/$cut.raw.mp4" -c:v copy \
    -af "loudnorm=I=-14:TP=-2:LRA=11:measured_I=$(get input_i):measured_TP=$(get input_tp):measured_LRA=$(get input_lra):measured_thresh=$(get input_thresh):offset=$(get target_offset):linear=true" \
    -c:a aac -b:a 192k -ar 48000 -movflags +faststart "$out/$cut.mp4"
  rm "$out/$cut.raw.mp4"
  npx remotion still src/index.ts "$slug-cover-$cut" "$out/cover-$cut.jpg" --image-format=jpeg --jpeg-quality=92 --log=error
  echo "$out/$cut.mp4"
done
bash scripts/sheet.sh "$out/shorts.mp4" "$out/sheet-shorts.jpg" 1 >/dev/null
bash scripts/sheet.sh "$out/feed.mp4" "$out/sheet-feed.jpg" 1 >/dev/null
echo "contact sheets: $out/sheet-shorts.jpg, $out/sheet-feed.jpg"
