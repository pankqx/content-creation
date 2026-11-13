#!/usr/bin/env bash
# Opens Clipzer in its own app window. Starts the server if it isn't running and stops it when the window closes.
# Built, developed & owned by K S Pankaj.
cd "$(dirname "$0")/.."
PORT="${CLIPZER_PORT:-8000}"
URL="http://127.0.0.1:$PORT"
LOG="$HOME/.local/share/clipzer/server.log"
mkdir -p "$(dirname "$LOG")"

notify() { command -v notify-send >/dev/null && notify-send -i "$PWD/web/icon.svg" "Clipzer" "$1"; echo "$1"; }

if [ ! -x .venv/bin/python ]; then
  notify "First start: installing Clipzer (a few minutes)…"
  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt \
    || { notify "Setup failed. Run ./run.sh in a terminal to see why."; exit 1; }
fi
[ -f .env ] || cp .env.example .env

STARTED=""
if ! curl -fs "$URL/api/health" >/dev/null 2>&1; then
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 &
  STARTED=$!
  for _ in $(seq 1 60); do curl -fs "$URL/api/health" >/dev/null 2>&1 && break; sleep 0.5; done
fi

PROFILE="$HOME/.local/share/clipzer/window"
for b in google-chrome google-chrome-stable chromium chromium-browser brave-browser microsoft-edge; do
  if command -v "$b" >/dev/null; then
    "$b" --app="$URL" --user-data-dir="$PROFILE" --class=Clipzer --window-size=1440,920 >/dev/null 2>&1
    OPENED=1; break
  fi
done
if [ -z "$OPENED" ]; then
  # No Chromium-family browser: open a normal tab and keep the server until this is closed.
  xdg-open "$URL" >/dev/null 2>&1
  [ -n "$STARTED" ] && { notify "Clipzer is running at $URL"; wait "$STARTED"; }
  exit 0
fi
[ -n "$STARTED" ] && kill "$STARTED" 2>/dev/null
exit 0
