#!/usr/bin/env bash
# Install and enable the J.A.R.V.I.S. systemd user service.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC="$REPO_DIR/systemd/jarvis.service"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_DST="$UNIT_DIR/jarvis.service"

echo "==> Installing jarvis.service …"
mkdir -p "$UNIT_DIR"
cp "$UNIT_SRC" "$UNIT_DST"
systemctl --user daemon-reload
systemctl --user enable --now jarvis.service
echo "==> Done. Service status:"
systemctl --user status jarvis.service --no-pager || true
echo
echo "Useful commands:"
echo "  systemctl --user status  jarvis"
echo "  systemctl --user restart jarvis"
echo "  systemctl --user stop    jarvis"
echo "  journalctl --user -u jarvis -f"
echo "  jarvis status"
echo "  jarvis ipc QUIT"
