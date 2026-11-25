#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start_deskpilot.sh — Launch DeskPilot (Linux Productivity Agent)
#
# Usage:
#   ./start_deskpilot.sh          — foreground (see output in terminal)
#   ./start_deskpilot.sh --bg     — background (logs to logs/deskpilot.log)
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

# Ensure Ollama is running (DeskPilot fails silently without it)
if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Ollama not running — starting it in background..."
    nohup ollama serve >> logs/ollama.log 2>&1 &
    echo "Waiting for Ollama to become ready..."
    for i in $(seq 1 15); do
        sleep 1
        if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "Ollama ready."
            break
        fi
        if [[ $i -eq 15 ]]; then
            echo "ERROR: Ollama failed to start after 15s. Check logs/ollama.log"
            exit 1
        fi
    done
elif ! command -v ollama &>/dev/null; then
    echo "WARNING: Ollama not found. Install: curl -fsSL https://ollama.com/install.sh | sh"
fi

# Launch
if [[ "${1:-}" == "--bg" ]]; then
    echo "Starting DeskPilot in background... (logs → logs/deskpilot.log)"
    nohup python -m src.deskpilot.main >> logs/deskpilot.log 2>&1 &
    echo "PID: $!"
else
    echo "Starting DeskPilot in foreground..."
    python -m src.deskpilot.main
fi
