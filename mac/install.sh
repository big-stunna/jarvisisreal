#!/usr/bin/env bash
# J.A.R.V.I.S. installer for macOS: deps, venv, Groq key, login service, hotkeys.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"
JARVIS="$VENV/bin/jarvis"
PLIST="$HOME/Library/LaunchAgents/com.jarvis.daemon.plist"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }

if ! command -v brew >/dev/null; then
  echo "Homebrew is required: https://brew.sh"; exit 1
fi

say "1/5  Installing system packages (portaudio, ffmpeg, brightness, skhd, python@3.12)"
brew install portaudio ffmpeg brightness python@3.12
brew install koekeishiya/formulae/skhd

say "2/5  Creating Python environment"
PY="$(brew --prefix python@3.12)/bin/python3.12"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -e "$ROOT" -q
mkdir -p "$HOME/.local/bin"
ln -sf "$JARVIS" "$HOME/.local/bin/jarvis"

say "3/5  Groq API key (free at console.groq.com — leave blank to use 'claude' CLI only)"
if ! grep -q '^GROQ_API_KEY=gsk_' "$ROOT/.env" 2>/dev/null; then
  read -rsp "Groq key: " key; echo
  if [[ -n "$key" ]]; then
    echo "GROQ_API_KEY=${key#"${key%%gsk_*}"}" >> "$ROOT/.env"
    echo "saved"
  fi
fi

say "4/5  Wake-word service (starts at login)"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.jarvis.daemon</string>
  <key>ProgramArguments</key>
  <array><string>$JARVIS</string><string>start</string><string>--no-hud</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/jarvis.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/jarvis.log</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/com.jarvis.daemon" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

say "5/5  Hotkeys: Cmd+Shift+J chat · Cmd+Shift+V voice · Cmd+Alt+J wake word on/off"
SKHD="$HOME/.skhdrc"
touch "$SKHD"
if ! grep -q "jarvis" "$SKHD"; then
  cat >> "$SKHD" <<EOF

# J.A.R.V.I.S.
cmd + shift - j : $JARVIS gui
cmd + shift - v : $JARVIS ask
cmd + alt - j   : $JARVIS toggle
EOF
fi
skhd --start-service 2>/dev/null || skhd --restart-service

cat <<EOF

Done. Three macOS permissions are needed (System Settings → Privacy & Security):
  • Microphone      → allow Terminal and python3.12 (prompted on first listen)
  • Accessibility   → allow skhd (for the hotkeys)
  • Automation      → allow python3.12 to control Music/Spotify (pausing media on lock)

Try:  jarvis ask      (voice popup)
      jarvis gui      (chat window)
      say "Hey Jarvis"
Logs: ~/Library/Logs/jarvis.log
EOF
