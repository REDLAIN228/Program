#!/usr/bin/env bash
set -euo pipefail
cd /workspace/Program
export UV_CACHE_DIR=/workspace/.cache/uv
export XDG_CACHE_HOME=/workspace/.cache
if command -v uv >/dev/null 2>&1; then
  uv venv --allow-existing --python python3 .venv
  uv pip install --python .venv/bin/python -r requirements-dev.txt
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements-dev.txt
fi
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
