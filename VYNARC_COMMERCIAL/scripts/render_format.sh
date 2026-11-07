#!/usr/bin/env bash
# Render one delivery format as 150-frame chunks with N parallel workers,
# then concatenate into a lossless-quality intermediate.
#   scripts/render_format.sh <name> <width> <height> <msaa> [workers]
# Re-running skips chunks that already exist (resume after interruption).
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=$1; W=$2; H=$3; MSAA=$4; WORKERS=${5:-2}
FRAMES=900; CHUNK=150
DIR=renders/chunks/$NAME
mkdir -p "$DIR"
NCH=$(( (FRAMES + CHUNK - 1) / CHUNK ))

worker() {
  local w=$1
  for ((c = w; c < NCH; c += WORKERS)); do
    local s=$(( c * CHUNK )) e=$(( (c + 1) * CHUNK ))
    (( e > FRAMES )) && e=$FRAMES
    local out=$DIR/chunk_$(printf %02d $c).mp4
    if [[ -s $out && -f $out.ok ]]; then echo "[$NAME] skip chunk $c"; continue; fi
    node scripts/render.mjs --width "$W" --height "$H" --msaa "$MSAA" --start $s --end $e \
      --crf 9 --preset medium --out "$out" 2>&1 | grep -E "frame|wrote|error|Error" | sed "s/^/[$NAME w$w] /"
    touch "$out.ok"
  done
}

for ((w = 0; w < WORKERS; w++)); do worker $w & done
wait
: > "$DIR/list.txt"
for ((c = 0; c < NCH; c++)); do echo "file 'chunk_$(printf %02d $c).mp4'" >> "$DIR/list.txt"; done
ffmpeg -v error -y -f concat -safe 0 -i "$DIR/list.txt" -c copy "renders/chunks/${NAME}_master_video.mp4"
echo "[$NAME] done -> renders/chunks/${NAME}_master_video.mp4"
