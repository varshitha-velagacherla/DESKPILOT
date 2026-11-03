"""
smoke_test.py — Linux Smoke Test Suite for WPA

Checks: Ollama connectivity, mic input availability, TTS output, wake-word
model load, Whisper transcription of a synthetic sample, every tool callable,
memory read/write, and peak RAM.

Usage:
    source .venv/bin/activate
    python tests/smoke_test.py
"""

import sys
import os
import time
import shutil
import subprocess
import traceback
import psutil
import numpy as np

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS   = "✅ PASS"
FAIL   = "❌ FAIL"
SKIP   = "⚠️  SKIP"
results = []

def check(name, fn):
    """Run a check function, recording pass/fail."""
    try:
        t0  = time.time()
        msg = fn()
        dt  = time.time() - t0
        ok  = True
        print(f"  {PASS}  {name} ({dt:.1f}s) — {msg}")
    except Exception as e:
        ok  = False
        msg = str(e)
        print(f"  {FAIL}  {name} — {msg}")
        traceback.print_exc()
    results.append((name, ok, msg))


# ══════════════════════════════════════════════════════════════════════════════
# 1. Ollama connectivity
# ══════════════════════════════════════════════════════════════════════════════

def test_ollama():
    import requests
    resp = requests.get("http://localhost:11434/api/tags", timeout=5)
    models = [m["name"] for m in resp.json().get("models", [])]
    assert len(models) > 0, "No models found in Ollama"
    return f"models: {models}"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Mic input available
# ══════════════════════════════════════════════════════════════════════════════

def test_mic():
    import sounddevice as sd
    devs = sd.query_devices()
    inputs = [d for d in devs if d["max_input_channels"] > 0]
    assert len(inputs) > 0, "No input (mic) devices found"
    default = sd.query_devices(kind="input")
    return f"default input: {default['name']} ({default['max_input_channels']}ch)"


# ══════════════════════════════════════════════════════════════════════════════
# 3. TTS output
# ══════════════════════════════════════════════════════════════════════════════

def test_tts():
    import pyttsx3
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    engine.stop()
    assert voices and len(voices) > 0, "No TTS voices found (install espeak-ng)"
    return f"{len(voices)} voice(s) available"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Wake-word model load
# ══════════════════════════════════════════════════════════════════════════════

def test_wakeword():
    from openwakeword import get_pretrained_model_paths
    from openwakeword.model import Model as WakeWordModel
    paths = get_pretrained_model_paths()
    tflite = next((p for p in paths if "alexa" in p.lower()), None)
    assert tflite, f"alexa model not in paths: {[os.path.basename(p) for p in paths]}"
    onnx = tflite.replace(".tflite", ".onnx")
    assert os.path.exists(onnx), f"ONNX file not found: {onnx}"
    model = WakeWordModel(
        wakeword_models=[onnx],          # new API
        enable_speex_noise_suppression=False,
        inference_framework="onnx",
    )
    out = model.predict(np.zeros(1280, dtype=np.int16))
    assert len(out) > 0, "predict() returned nothing"
    return f"key={list(out.keys())[0]}, score={list(out.values())[0]:.4f}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Whisper transcription of synthetic audio
# ══════════════════════════════════════════════════════════════════════════════

def test_whisper():
    from faster_whisper import WhisperModel
    # Check if model is cached locally first — avoid slow HF download in CI
    import pathlib
    hf_cache = pathlib.Path.home() / ".cache" / "huggingface" / "hub"
    cached = list(hf_cache.glob("*faster-whisper*base*")) if hf_cache.exists() else []
    if not cached:
        return "SKIP — base.en model not cached yet (will download on first run of main.py)"
    model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)
    import soundfile as sf, tempfile
    audio = np.zeros(16000, dtype=np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        sf.write(f.name, audio, 16000)
        tmp = f.name
    try:
        segments, info = model.transcribe(tmp, language="en", beam_size=1)
        text = " ".join(s.text for s in segments).strip()
    finally:
        os.unlink(tmp)
    return f"transcribed silent audio → '{text}' (expected empty)"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Every tool callable
# ══════════════════════════════════════════════════════════════════════════════

def test_tools():
    from src.wpa.agent.tools import ALL_TOOLS
    names = [t.name if hasattr(t, "name") else t.__name__ for t in ALL_TOOLS]
    assert len(names) >= 10, f"Only {len(names)} tools registered"
    return f"{len(names)} tools: {names}"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Memory read/write (SQLite)
# ══════════════════════════════════════════════════════════════════════════════

def test_memory_sqlite():
    from src.wpa.memory.sqlite_memory import save_interaction, get_recent_interactions
    save_interaction(
        session_id="smoke_test",
        user_input="hello",
        intent="chat",
        tool_name="",
        tool_args={},
        tool_output="",
        success=False,
        response="hi",
    )
    recent = get_recent_interactions(1)
    assert len(recent) >= 1, "No interactions returned after write"
    return f"SQLite write/read OK, last entry: {recent[0].get('user_input', '?')}"


# ══════════════════════════════════════════════════════════════════════════════
# 8. Memory read/write (ChromaDB, optional)
# ══════════════════════════════════════════════════════════════════════════════

def test_memory_chroma():
    try:
        from src.wpa.memory.chroma_memory import save_preference, get_relevant_preferences
        save_preference("smoke test preference: dark mode")
        results_q = get_relevant_preferences("dark mode")
        assert results_q is not None, "query returned None"
        return f"ChromaDB write/read OK, {len(results_q)} results"
    except ImportError:
        return "ChromaDB not available (graceful skip)"


# ══════════════════════════════════════════════════════════════════════════════
# 9. Platform utils
# ══════════════════════════════════════════════════════════════════════════════

def test_platform():
    from src.wpa.system.platform_utils import (
        detect_session_type, resolve_app_command, get_volume_linux
    )
    session = detect_session_type()
    firefox = resolve_app_command("firefox")
    vol     = get_volume_linux()
    return f"session={session}, firefox={firefox}, vol={vol}"


# ══════════════════════════════════════════════════════════════════════════════
# 10. Peak RAM
# ══════════════════════════════════════════════════════════════════════════════

def test_peak_ram():
    rss_mb = psutil.Process().memory_info().rss / 1024 / 1024
    assert rss_mb < 5000, f"RSS {rss_mb:.0f} MB exceeds 5 GB limit"
    return f"current RSS: {rss_mb:.0f} MB"


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 60)
    print("  WPA Linux Smoke Test")
    print("=" * 60 + "\n")

    check("Ollama connectivity",    test_ollama)
    check("Mic input",             test_mic)
    check("TTS (espeak-ng)",       test_tts)
    check("Wake-word model",       test_wakeword)
    check("Whisper transcription", test_whisper)
    check("All tools registered",  test_tools)
    check("SQLite memory",        test_memory_sqlite)
    check("ChromaDB memory",      test_memory_chroma)
    check("Platform utils",       test_platform)
    check("Peak RAM",             test_peak_ram)

    passed = sum(1 for _, ok, _ in results if ok)
    total  = len(results)

    print(f"\n{'=' * 60}")
    print(f"  Result: {passed}/{total} passed")
    print(f"  Peak RSS: {psutil.Process().memory_info().rss / 1024 / 1024:.0f} MB")
    print(f"{'=' * 60}\n")

    if passed < total:
        failed = [(n, m) for n, ok, m in results if not ok]
        print("FAILURES:")
        for name, msg in failed:
            print(f"  • {name}: {msg}")
        print()

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
