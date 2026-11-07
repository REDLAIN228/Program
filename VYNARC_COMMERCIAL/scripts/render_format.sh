#!/usr/bin/env bash
# Render one delivery format as 150-frame chunks with N parallel workers,
# then concatenate into a high-quality intermediate.
#   scripts/render_format.sh <name> <width> <height> <msaa> [workers]
# Re-running skips chunks that already finished (marker file chunk_NN.mp4.ok).
set -uo pipefail
cd "$(dirname "$0")/.."
NAME=$1; W=$2; H=$3; MSAA=$4; WORKERS=${5:-2}
FRAMES=${FRAMES:-900}; CHUNK=${CHUNK:-150}
DIR=renders/chunks/$NAME
mkdir -p "$DIR"
NCH=$(( (FRAMES + CHUNK - 1) / CHUNK ))

render_chunk() {
  local c=$1 w=$2
  local s=$(( c * CHUNK )) e=$(( (c + 1) * CHUNK ))
  (( e > FRAMES )) && e=$FRAMES
  local out=$DIR/chunk_$(printf %02d "$c").mp4
  for attempt in 1 2 3; do
    node scripts/render.mjs --width "$W" --height "$H" --msaa "$MSAA" --start $s --end $e \
      --crf 9 --preset medium --out "$out" 2>&1 | grep --line-buffered -v "GL Driver" | sed -u "s/^/[$NAME w$w c$c] /"
    if [[ ${PIPESTATUS[0]} -eq 0 ]] && ffprobe -v error -count_frames -select_streams v:0 \
         -show_entries stream=nb_read_frames -of csv=p=0 "$out" | grep -qx "$(( e - s ))"; then
      touch "$out.ok"; return 0
    fi
    echo "[$NAME w$w c$c] attempt $attempt failed, retrying"
  done
  echo "[$NAME] chunk $c FAILED"; return 1
}

worker() {
  local w=$1 rc=0
  for ((c = w; c < NCH; c += WORKERS)); do
    if [[ -f $DIR/chunk_$(printf %02d $c).mp4.ok ]]; then echo "[$NAME] skip chunk $c"; continue; fi
    render_chunk "$c" "$w" || rc=1
  done
  return $rc
}

pids=()
for ((w = 0; w < WORKERS; w++)); do worker $w & pids+=($!); done
fail=0
for p in "${pids[@]}"; do wait "$p" || fail=1; done
(( fail )) && { echo "[$NAME] some chunks failed"; exit 1; }
: > "$DIR/list.txt"
for ((c = 0; c < NCH; c++)); do echo "file 'chunk_$(printf %02d $c).mp4'" >> "$DIR/list.txt"; done
ffmpeg -v error -y -f concat -safe 0 -i "$DIR/list.txt" -c copy "renders/chunks/${NAME}_master_video.mp4" || exit 1
echo "[$NAME] done -> renders/chunks/${NAME}_master_video.mp4 ($(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 renders/chunks/${NAME}_master_video.mp4) frames)"
