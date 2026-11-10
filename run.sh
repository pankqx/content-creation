#!/usr/bin/env bash
# Starts Clipzer on Linux or macOS. First run sets everything up.
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "Install ffmpeg first:  sudo apt install ffmpeg"; exit 1; }
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
[ -f .env ] || cp .env.example .env
echo "Clipzer is starting at http://localhost:8000"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
