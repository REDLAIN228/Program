#!/usr/bin/env bash
# Full reproducible production: textures -> audio -> all formats -> deliverables -> QA.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/trace_logo.py
node scripts/build_ui.mjs
python3 scripts/synth_audio.py
scripts/render_format.sh landscape4k 3840 2160 0 2
scripts/render_format.sh portrait 1080 1920 4 2
scripts/render_format.sh square 1080 1080 4 2
scripts/encode_deliverables.sh
python3 scripts/qa_check.py
