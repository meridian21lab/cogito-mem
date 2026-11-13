#!/usr/bin/env bash
# Contact sheet of a render: one thumbnail every N seconds (default 1), 8 per row, left to right, top to bottom.
#   bash scripts/sheet.sh out/<film>/shorts.mp4 out/<film>/sheet.jpg [seconds]
set -euo pipefail
in=${1:?usage: sheet.sh video.mp4 sheet.jpg [seconds]}
out=${2:?usage: sheet.sh video.mp4 sheet.jpg [seconds]}
every=${3:-1}
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$in")
n=$(python3 -c "import math; print(math.ceil($dur / $every))")
rows=$(( (n + 7) / 8 ))
ffmpeg -v error -y -i "$in" -vf "fps=1/$every,scale=240:-1,tile=8x$rows:padding=4:color=white" -frames:v 1 -q:v 3 "$out"
echo "$out ($n frames, every $every s)"
