#!/usr/bin/env bash
# One-time setup: Python venv, Python deps, HyperFrames CLI, Robust Video Matting model.
# Requires: macOS on Apple Silicon (mlx-whisper), Python 3.12+, Node 20+, FFmpeg (brew install ffmpeg).
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# local npm cache avoids permission problems with a root-owned ~/.npm
export npm_config_cache="$PWD/.npm-cache"
npm install

# Robust Video Matting (GPL-3.0, https://github.com/PeterL1n/RobustVideoMatting) — downloaded, not bundled
mkdir -p models
if [ ! -f models/rvm_mobilenetv3_fp32.torchscript ]; then
  curl -fL -o models/rvm_mobilenetv3_fp32.torchscript \
    https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_mobilenetv3_fp32.torchscript
fi

npx hyperframes doctor || true
echo "✓ setup done — activate with: source .venv/bin/activate"
