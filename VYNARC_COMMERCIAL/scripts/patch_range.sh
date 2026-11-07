#!/usr/bin/env bash
# Re-render a frame range [START, END) of one format and splice it into that
# format's master intermediate (every frame is a pure function of time, so a
# patch is identical to a full re-render of those frames).
#   scripts/patch_range.sh <name> <width> <height> <msaa> <start> <end>
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=$1; W=$2; H=$3; MSAA=$4; S=$5; E=$6
C=renders/chunks
M=$C/${NAME}_master_video.mp4
P=$C/${NAME}_patch_${S}_${E}.mp4
node scripts/render.mjs --width "$W" --height "$H" --msaa "$MSAA" --start "$S" --end "$E" --crf 9 --preset medium --out "$P" \
  2>&1 | grep -v "GL Driver" | grep -E "wrote|retry|rror" || true
N=$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 "$P")
[[ $N -eq $(( E - S )) ]] || { echo "patch has $N frames, expected $(( E - S ))"; exit 1; }
ffmpeg -v error -y -i "$M" -i "$P" -filter_complex \
  "[0:v]trim=end_frame=$S,setpts=PTS-STARTPTS[a];[1:v]setpts=PTS-STARTPTS[b];[0:v]trim=start_frame=$E,setpts=PTS-STARTPTS[c];[a][b][c]concat=n=3:v=1:a=0[v]" \
  -map "[v]" -r 60 -c:v libx264 -preset medium -crf 9 -pix_fmt yuv420p -profile:v high -tune film -x264-params aq-mode=3:deblock=-1,-1 \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 "$M.tmp.mp4"
N2=$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 "$M.tmp.mp4")
[[ $N2 -eq 900 ]] || { echo "spliced master has $N2 frames"; exit 1; }
mv "$M.tmp.mp4" "$M"
echo "[$NAME] patched frames $S-$E"
