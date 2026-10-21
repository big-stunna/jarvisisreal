#!/usr/bin/env bash
# Full J.A.R.V.I.S. setup: venv, dependencies, optional models, service.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_DIR/.venv"

echo "==> J.A.R.V.I.S. installer"
echo "    Repo: $REPO_DIR"
echo

# ── Python venv ──────────────────────────────────────────────────────────────
if [[ ! -d "$VENV" ]]; then
    echo "==> Creating Python venv …"
    python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"

echo "==> Installing Python dependencies …"
pip install --quiet --upgrade pip
pip install --quiet -e "$REPO_DIR"
pip install --quiet \
    faster-whisper \
    sounddevice \
    soundfile \
    edge-tts

echo "==> Dependencies installed."

# ── Ollama model check ────────────────────────────────────────────────────────
if command -v ollama &>/dev/null; then
    if ! ollama list 2>/dev/null | grep -q "qwen2.5:7b"; then
        echo "==> Pulling qwen2.5:7b (offline brain model) …"
        ollama pull qwen2.5:7b
    else
        echo "==> qwen2.5:7b already present."
    fi
else
    echo "  [skip] ollama not found — install it for offline mode."
fi

# ── faster-whisper base model (pre-download) ──────────────────────────────────
echo "==> Pre-downloading faster-whisper 'base' model …"
python3 -c "
from faster_whisper import WhisperModel
WhisperModel('base', device='cpu', compute_type='int8')
print('  whisper base model ready.')
" 2>/dev/null || echo "  [skip] whisper model download failed (run jarvis voice once to trigger it)."

# ── .env ──────────────────────────────────────────────────────────────────────
if [[ ! -f "$REPO_DIR/.env" ]]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env" 2>/dev/null || cat > "$REPO_DIR/.env" << 'ENV'
# J.A.R.V.I.S. API Keys
GROQ_API_KEY=your_groq_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
GEMINI_API_KEY=your_gemini_key_here
OPENAI_API_KEY=your_openai_key_here
ENV
    echo "==> Created .env — fill in your API keys."
else
    echo "==> .env already exists."
fi

# ── systemd service ───────────────────────────────────────────────────────────
echo
read -r -p "Install and enable systemd user service? [y/N] " reply
if [[ "${reply,,}" == "y" ]]; then
    bash "$REPO_DIR/scripts/install-service.sh"
else
    echo "  Skipped. Run 'bash scripts/install-service.sh' later."
fi

echo
echo "==> Setup complete!"
echo "    To start now:    jarvis voice --offline"
echo "    Chat mode:       jarvis chat --offline"
echo "    Daemon:          jarvis daemon --offline"
echo "    Status:          jarvis status"
