#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start_wpa.sh — Launch the Linux Productivity Agent (WPA)
#
# Usage:
#   ./start_wpa.sh          — foreground (see output in terminal)
#   ./start_wpa.sh --bg     — background (logs to logs/wpa.log)
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [[ -d ".venv" ]]; then
    source .venv/bin/activate
else
    echo "ERROR: .venv not found. Run: python3.11 -m venv .venv --system-site-packages"
    exit 1
fi

# Ensure logs directory
mkdir -p logs

# Check Ollama
if ! command -v ollama &>/dev/null; then
    echo "WARNING: Ollama not found. Install: curl -fsSL https://ollama.com/install.sh | sh"
fi

# Launch
if [[ "${1:-}" == "--bg" ]]; then
    echo "Starting WPA in background... (logs → logs/wpa.log)"
    nohup python -m src.wpa.main >> logs/wpa.log 2>&1 &
    echo "PID: $!"
else
    echo "Starting WPA in foreground..."
    python -m src.wpa.main
fi
