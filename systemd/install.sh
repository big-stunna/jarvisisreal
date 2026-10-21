#!/usr/bin/env bash
set -e

UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
cp "$(dirname "$0")/jarvis.service" "$UNIT_DIR/jarvis.service"
systemctl --user daemon-reload
systemctl --user enable jarvis.service
systemctl --user start jarvis.service
echo "J.A.R.V.I.S. service installed and started."
echo "Toggle with: jarvis toggle   OR   Super+J keybind"
