#!/usr/bin/env bash
# Adds Clipzer to the Ubuntu app menu (and optionally the desktop). Run once:  ./desktop/install.sh
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
chmod +x "$HERE/desktop/clipzer-launch.sh" "$HERE/run.sh"

missing=()
command -v ffmpeg >/dev/null || missing+=(ffmpeg)
command -v python3 >/dev/null || missing+=(python3)
python3 -c "import venv, ensurepip" 2>/dev/null || missing+=(python3-venv)
fc-list | grep -qi "Noto Sans Kannada" || missing+=(fonts-noto-core)
command -v notify-send >/dev/null || missing+=(libnotify-bin)
if [ ${#missing[@]} -gt 0 ]; then
  echo "Installing: ${missing[*]}  (needs your password)"
  sudo apt-get update -qq && sudo apt-get install -y "${missing[@]}"
fi

APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
cat > "$APPS/clipzer.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Clipzer
GenericName=AI video clipper
Comment=Turn long videos into captioned shorts. By K S Pankaj.
Exec="$HERE/desktop/clipzer-launch.sh"
Icon=$HERE/web/icon.svg
Terminal=false
Categories=AudioVideo;Video;AudioVideoEditing;
StartupWMClass=Clipzer
Keywords=clips;shorts;video;captions;youtube;
DESKTOP
chmod +x "$APPS/clipzer.desktop"
update-desktop-database "$APPS" >/dev/null 2>&1 || true

DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESK" ]; then
  cp "$APPS/clipzer.desktop" "$DESK/clipzer.desktop"
  chmod +x "$DESK/clipzer.desktop"
  gio set "$DESK/clipzer.desktop" metadata::trusted true 2>/dev/null || true
fi

echo
echo "Done. Open Clipzer from the app menu (press Super, type Clipzer)."
echo "The first start installs Python packages, so give it a few minutes."
