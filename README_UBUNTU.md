# WPA — Linux Productivity Agent (Ubuntu Port)

An offline-first voice assistant ported from Windows to Ubuntu.  
Says a wake word → records speech → transcribes with Whisper → classifies intent via Ollama → executes tools deterministically → responds via TTS.

## Quick Start

```bash
cd ~/Desktop/Windows-Productivity-Agent-main

# 1. Fix EOL apt sources (Ubuntu 23.10 is end-of-life)
# If apt update fails, replace archive.ubuntu.com with old-releases.ubuntu.com:
sudo cp /etc/apt/sources.list /etc/apt/sources.list.bak
sudo sed -i 's|archive.ubuntu.com|old-releases.ubuntu.com|g' /etc/apt/sources.list
sudo sed -i 's|security.ubuntu.com|old-releases.ubuntu.com|g' /etc/apt/sources.list
sudo apt update

# 2. Install system dependencies
sudo apt install -y python3-venv python3-dev python3.11-venv python3.11-dev \
  build-essential portaudio19-dev libportaudio2 libsndfile1 ffmpeg espeak-ng \
  xclip xsel wl-clipboard wmctrl xdotool pulseaudio-utils playerctl \
  gir1.2-appindicator3-0.1 python3-gi libgirepository1.0-dev libcairo2-dev

# 3. Install Ollama + models
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:1.5b
# Optional, better quality (needs ~3 GB more RAM):
# ollama pull qwen2.5:3b

# 4. Create venv and install Python packages
python3.11 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements_linux.txt

# 5. Configure
cp .env.example .env   # or use the .env already provided
# Edit .env: set OLLAMA_MODEL, WAKE_WORD, etc.

# 6. Run
./start_wpa.sh
```

## Running

| Mode | Command |
|------|---------|
| Foreground | `./start_wpa.sh` |
| Background | `./start_wpa.sh --bg` |
| Dev mode | `source .venv/bin/activate && python -m src.wpa.main` |
| Smoke test | `source .venv/bin/activate && python tests/smoke_test.py` |

## Autostart at Login

### Option A: XDG Desktop Entry
```bash
cp wpa.desktop ~/.config/autostart/
```

### Option B: systemd --user unit
```bash
cp wpa.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable wpa.service
systemctl --user start wpa.service
# Check status:
systemctl --user status wpa.service
journalctl --user -u wpa.service -f
```

## System Tray

Requires `gir1.2-appindicator3-0.1` and `python3-gi` (installed in step 2).

On **GNOME + Wayland**, also install the AppIndicator extension:
```bash
sudo apt install gnome-shell-extension-appindicator
# Then enable it in GNOME Extensions or restart GNOME Shell
```

If the tray icon doesn't appear, try logging in with **"Ubuntu on Xorg"** (gear icon at the GDM login screen).

## X11 vs Wayland

| Feature | X11 | Wayland |
|---------|-----|---------|
| System tray | ✅ Full | ⚠️ Needs AppIndicator extension |
| Window listing (wmctrl) | ✅ Full | ❌ Falls back to psutil |
| Clipboard (xclip) | ✅ Full | ✅ Uses wl-clipboard |
| Screenshots (mss) | ✅ Full | ✅ Works on most compositors |

**To switch to Xorg**: At the GDM login screen, click the gear icon (bottom-right) and select **"Ubuntu on Xorg"**.

## CPU / 8 GB RAM Performance Tips

| Setting | Value | Notes |
|---------|-------|-------|
| Whisper model | `base.en` | Change to `tiny.en` for speed, `small.en` for accuracy |
| Whisper compute | `int8` | Quantized for CPU |
| Whisper beam_size | `1` | Greedy decode (fastest) |
| Whisper cpu_threads | `4` | Matches Ryzen 3 3250U |
| Ollama model | `qwen2.5:1.5b` | Fits in ~1 GB RAM. Use `qwen2.5:3b` for better quality |
| PyTorch | CPU-only | No CUDA/ROCm packages |
| openwakeword | ONNX backend | tflite unavailable on Python 3.11 |

### Swap

If swap < 4 GB:
```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `apt update` fails | Fix EOL sources (see Quick Start step 1) |
| No sound / mic | Check `pactl list sources short` or `wpctl status` |
| Ollama not reachable | Run `ollama serve` in a terminal |
| TTS too fast | Lower rate in `src/wpa/voice/tts.py` (default: 160 wpm) |
| Wake word not detecting | Lower `WAKE_WORD_THRESHOLD` in `.env` (default: 0.05) |
| High RAM usage | Switch to `tiny.en` Whisper and `qwen2.5:1.5b` Ollama |
| Tray icon missing | Install AppIndicator extension or switch to Xorg |
| `ModuleNotFoundError: gi` | Venv must use `--system-site-packages` |

## Architecture

```
Wake word (openwakeword/ONNX)
  → Faster Whisper STT (base.en / CPU / int8)
  → LLM intent classifier (Ollama qwen2.5:1.5b)
  → Deterministic Python router
  → Deterministic tool execution
  → LLM response generator (Ollama qwen2.5:1.5b)
  → TTS (pyttsx3 / espeak-ng)
```

Memory: SQLite (episodic) + ChromaDB (semantic, sentence-transformers).  
All processing offline after initial model downloads.

## Files Changed from Windows → Linux

| File | Change |
|------|--------|
| `src/wpa/system/platform_utils.py` | **NEW** — Linux abstraction layer |
| `src/wpa/agent/tools/system_tools.py` | `pyautogui` → `wpctl`/`pactl`/`amixer`; `pyperclip` → `xclip`/`wl-clipboard` |
| `src/wpa/agent/tools/app_tools.py` | Windows `.exe` map → Linux `shutil.which()` map |
| `src/wpa/agent/tool_executor.py` | Windows `C:\` APP_MAP → Linux `resolve_app_command()` |
| `src/wpa/agent/tools/screen_tools.py` | Hardcoded `C:\Users\…` → `~/Pictures/Screenshots` |
| `src/wpa/voice/tts.py` | SAPI5 Zira → espeak-ng |
| `src/wpa/voice/stt.py` | `small` → `base.en`, forced CPU, `beam_size=1` |
| `src/wpa/voice/wakeword.py` | Added `inference_framework="onnx"` |
| `src/wpa/ui/tray.py` | `explorer` → `xdg-open`; title renamed |
| `src/wpa/main.py` | Default model/wake word; Wayland log; title renamed |
| `src/wpa/agent/intent_classifier.py` | "Windows" → "Linux" in prompt |
| `src/wpa/agent/response_generator.py` | Model fallback; "Windows" → "Linux" in prompt |
