#!/usr/bin/env bash
# Mux the synthesized soundtrack and encode the delivery files.
set -euo pipefail
cd "$(dirname "$0")/.."
A=audio/vynarc_sound.wav
C=renders/chunks
mkdir -p renders
COMMON=(-movflags +faststart -c:a aac -b:a 320k -ar 48000 -color_primaries bt709 -color_trc bt709 -colorspace bt709 -shortest)
X264=(-c:v libx264 -preset slow -profile:v high -pix_fmt yuv420p -tune film -x264-params aq-mode=3:deblock=-1,-1)

if [[ -f $C/landscape4k_master_video.mp4 ]]; then
  # 4K master. Size budget: GitHub rejects files > 100 MB, so H.264 is a
  # two-pass 44 Mbit/s encode (YouTube's 4K60 SDR range is 35-68 Mbit/s)
  # and H.265 is CRF 17 capped at 28 Mbit/s.
  ffmpeg -v error -y -i $C/landscape4k_master_video.mp4 "${X264[@]}" -level 5.2 -b:v 44M -maxrate 60M -bufsize 120M \
    -pass 1 -passlogfile $C/x264_4k -an -f mp4 /dev/null
  ffmpeg -v error -y -i $C/landscape4k_master_video.mp4 -i $A "${X264[@]}" -level 5.2 -b:v 44M -maxrate 60M -bufsize 120M \
    -pass 2 -passlogfile $C/x264_4k "${COMMON[@]}" renders/VYNARC_commercial_4K_60fps_H264.mp4
  ffmpeg -v error -y -i $C/landscape4k_master_video.mp4 -i $A -c:v libx265 -preset slow -crf 17 -pix_fmt yuv420p -tag:v hvc1 \
    -x265-params log-level=error:aq-mode=3:vbv-maxrate=28000:vbv-bufsize=56000 "${COMMON[@]}" renders/VYNARC_commercial_4K_60fps_H265.mp4
  # YouTube 1080p: supersampled down from the 4K master
  ffmpeg -v error -y -i $C/landscape4k_master_video.mp4 -i $A -vf "scale=1920:1080:flags=lanczos" "${X264[@]}" -level 4.2 -crf 15 \
    -maxrate 40M -bufsize 80M "${COMMON[@]}" renders/VYNARC_commercial_YouTube_1920x1080_60fps.mp4
fi
if [[ -f $C/portrait_master_video.mp4 ]]; then
  ffmpeg -v error -y -i $C/portrait_master_video.mp4 -i $A "${X264[@]}" -level 4.2 -crf 16 -maxrate 30M -bufsize 60M \
    "${COMMON[@]}" renders/VYNARC_commercial_TikTok_Shorts_1080x1920_60fps.mp4
fi
if [[ -f $C/square_master_video.mp4 ]]; then
  ffmpeg -v error -y -i $C/square_master_video.mp4 -i $A "${X264[@]}" -level 4.2 -crf 16 -maxrate 25M -bufsize 50M \
    "${COMMON[@]}" renders/VYNARC_commercial_Square_1080x1080_60fps.mp4
fi
ls -la renders/*.mp4
