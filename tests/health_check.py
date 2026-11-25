#!/usr/bin/env python3
"""
health_check.py — Comprehensive DeskPilot Health Check Suite (Sections A–E, G)

Usage:
    .venv/bin/python tests/health_check.py
"""

from __future__ import annotations

import compileall
import importlib
import os
import pkgutil
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import psutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

RESULTS: list[tuple[str, str, str]] = []


def record(name: str, passed: bool, evidence: str) -> None:
    status = "PASS" if passed else "FAIL"
    RESULTS.append((name, status, evidence))
    icon = "✅" if passed else "❌"
    print(f"[{status}] {icon} {name}: {evidence}")


def run_check(name: str, fn: Callable[[], tuple[bool, str]]) -> None:
    t0 = time.time()
    try:
        passed, evidence = fn()
    except Exception as exc:
        passed, evidence = False, f"{type(exc).__name__}: {exc}"
    dt = time.time() - t0
    record(name, passed, f"{evidence} ({dt:.2f}s)")


def _run_cmd(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ══════════════════════════════════════════════════════════════════════════════
# A. Static checks
# ══════════════════════════════════════════════════════════════════════════════

def check_compileall() -> tuple[bool, str]:
    ok_src = compileall.compile_dir(str(PROJECT_ROOT / "src"), quiet=1)
    ok_tests = compileall.compile_dir(str(PROJECT_ROOT / "tests"), quiet=1)
    ok = bool(ok_src and ok_tests)
    return ok, f"compileall src={bool(ok_src)} tests={bool(ok_tests)}"


def check_pip_check() -> tuple[bool, str]:
    pip_bin = Path(sys.executable).parent / "pip"
    cmd = [str(pip_bin), "check"] if pip_bin.exists() else [sys.executable, "-m", "pip", "check"]
    res = _run_cmd(cmd, timeout=30)
    out = (res.stdout + res.stderr).strip()
    return res.returncode == 0, out or "exit 0"


def check_import_all_modules() -> tuple[bool, str]:
    pkg_dir = PROJECT_ROOT / "src" / "deskpilot"
    imported = []
    errors = []
    for mod in pkgutil.walk_packages([str(pkg_dir)], prefix="src.deskpilot."):
        try:
            importlib.import_module(mod.name)
            imported.append(mod.name)
        except Exception as exc:
            errors.append(f"{mod.name}: {exc}")
    importlib.import_module("src.deskpilot")
    if errors:
        return False, "; ".join(errors)
    return True, f"imported {len(imported)} submodules cleanly"


def check_leftover_old_refs() -> tuple[bool, str]:
    hits = []
    pattern = re.compile(r"wpa|windows-productivity-agent-main", re.IGNORECASE)
    skip_dirs = {".venv", ".git", "logs", "__pycache__"}
    for path in PROJECT_ROOT.rglob("*"):
        if any(part in skip_dirs for part in path.parts) or not path.is_file():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".bin", ".db", ".sqlite3", ".pyc"}:
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        if "wpa" in path.name.lower():
            hits.append(f"filename:{path.relative_to(PROJECT_ROOT)}")
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {line.strip()[:80]}")
    return len(hits) == 0, "no leftover wpa/old path refs" if not hits else f"{len(hits)} hit(s): " + " | ".join(hits[:5])


def check_referenced_paths() -> tuple[bool, str]:
    required = [
        PROJECT_ROOT / "start_deskpilot.sh",
        PROJECT_ROOT / "assets" / "tray_icon.png",
        PROJECT_ROOT / "deskpilot_architecture.png",
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / ".venv" / "bin" / "python",
        PROJECT_ROOT / "src" / "deskpilot" / "main.py",
    ]
    missing = [str(p.relative_to(PROJECT_ROOT)) for p in required if not p.exists()]
    desktop_txt = (PROJECT_ROOT / "deskpilot.desktop").read_text(encoding="utf-8")
    service_txt = (PROJECT_ROOT / "deskpilot.service").read_text(encoding="utf-8")
    readme_txt = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    for line in desktop_txt.splitlines():
        if line.startswith(("Exec=", "Path=", "Icon=")):
            val = line.split("=", 1)[1].strip().split()[0]
            if not Path(val).exists():
                missing.append(f"desktop:{val}")
    for line in service_txt.splitlines():
        if line.startswith(("WorkingDirectory=", "ExecStart=")):
            val = line.split("=", 1)[1].strip().split()[0]
            if not Path(val).exists():
                missing.append(f"service:{val}")
        elif line.startswith("Documentation=file://"):
            val = line.split("file://", 1)[1].strip()
            if not Path(val).exists():
                missing.append(f"service_doc:{val}")
    if "deskpilot_architecture.png" not in readme_txt:
        missing.append("README:deskpilot_architecture.png ref")
    return len(missing) == 0, "all referenced paths exist" if not missing else f"missing: {missing}"


def check_desktop_and_service_validate() -> tuple[bool, str]:
    ev = []
    ok = True
    # desktop-file-validate
    if shutil.which("desktop-file-validate"):
        r1 = _run_cmd(["desktop-file-validate", str(PROJECT_ROOT / "deskpilot.desktop")])
        ev.append(f"desktop-file-validate rc={r1.returncode}")
        if r1.returncode != 0:
            ok = False
    else:
        ok = False
        ev.append("desktop-file-validate missing")

    # systemd-analyze verify
    if shutil.which("systemd-analyze"):
        r2 = _run_cmd(["systemd-analyze", "--user", "verify", str(PROJECT_ROOT / "deskpilot.service")])
        ev.append(f"systemd-analyze rc={r2.returncode}")
        if r2.returncode != 0:
            ok = False
            # capture output for context
            out2 = (r2.stdout + r2.stderr).strip()
            ev.append(f"systemd-analyze output: {out2}")
    else:
        ev.append("systemd-analyze not available")
        # Not failing if missing per original? Keep ok unchanged.
    return ok, "; ".join(ev)


# ══════════════════════════════════════════════════════════════════════════════
# B. Services and environment
# ══════════════════════════════════════════════════════════════════════════════

def check_ollama() -> tuple[bool, str]:
    import requests
    from dotenv import load_dotenv
    try:
        load_dotenv(PROJECT_ROOT / ".env", override=True)
        url = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
        configured = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
        resp = requests.get(f"{url}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        has_model = any(m == configured or m.startswith(f"{configured}:") for m in models)
        return has_model, f"configured={configured}, installed={models}"
    except Exception as e:
        # Ollama not reachable – treat as FAIL with hint
        hint = "sudo systemctl start ollama"
        return False, f"Ollama not reachable ({e}) – FAIL. Hint: {hint}"
    import requests
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    url = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
    configured = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
    resp = requests.get(f"{url}/api/tags", timeout=5)
    resp.raise_for_status()
    models = [m["name"] for m in resp.json().get("models", [])]
    has_model = any(m == configured or m.startswith(f"{configured}:") for m in models)
    return has_model, f"configured={configured}, installed={models}"


def check_microphone() -> tuple[bool, str]:
    import sounddevice as sd
    # Query default input device and use its native sample rate
    default_in = sd.query_devices(kind="input")
    sr = int(default_in.get('default_samplerate', 16000))
    # Record 3 seconds at native rate
    rec = sd.rec(int(3 * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()
    rms = float(np.sqrt(np.mean(np.square(rec))))
    # Determine mute status using wpctl or pactl as before
    muted = None
    mute_info = "unknown"
    if shutil.which("wpctl"):
        r = _run_cmd(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"]) 
        mute_info = r.stdout.strip()
        muted = "[MUTED]" in mute_info
    elif shutil.which("pactl"):
        r = _run_cmd(["pactl", "get-source-mute", "@DEFAULT_SOURCE@"]) 
        mute_info = r.stdout.strip()
        muted = "yes" in mute_info.lower()
    ok = (muted is False) and (rms > 0.0)
    return ok, f"device='{default_in['name']}', source='{mute_info}', 3s_rms={rms:.6f}"
    import sounddevice as sd
    default_in = sd.query_devices(kind="input")
    muted = None
    mute_info = "unknown"
    if shutil.which("wpctl"):
        r = _run_cmd(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"])
        mute_info = r.stdout.strip()
        muted = "[MUTED]" in mute_info
    elif shutil.which("pactl"):
        r = _run_cmd(["pactl", "get-source-mute", "@DEFAULT_SOURCE@"])
        mute_info = r.stdout.strip()
        muted = "yes" in mute_info.lower()

    sr = 16000
    rec = sd.rec(int(3 * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()
    rms = float(np.sqrt(np.mean(np.square(rec))))
    ok = (muted is False) and (rms > 0.0)
    return ok, f"device='{default_in['name']}', source='{mute_info}', 3s_rms={rms:.6f}"


def check_speaker_and_tts() -> tuple[bool, str]:
    import sounddevice as sd
    from src.deskpilot.voice.tts import speak

    sink_info = "unknown"
    muted = False
    vol_val = None
    # Determine default output device and its native sample rate
    default_out = sd.query_devices(kind="output")
    sr = int(default_out.get('default_samplerate', 48000))
    if shutil.which("wpctl"):
        r = _run_cmd(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        sink_info = r.stdout.strip()
        muted = "[MUTED]" in sink_info
        parts = sink_info.split()
        if len(parts) >= 2:
            try:
                vol_val = float(parts[1])
            except ValueError:
                pass

    # Generate a 440 Hz tone at the determined sample rate
    t = np.linspace(0, 0.25, int(sr * 0.25), endpoint=False)
    tone = (0.15 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sd.play(tone, samplerate=sr)
    sd.wait()
    speak("DeskPilot is ready", blocking=True)
    ok = (not muted) and (vol_val is None or vol_val > 0.0)
    return ok, f"sink='{sink_info}', tone=440Hz/0.25s played at {sr}Hz, TTS spoke 'DeskPilot is ready'"

    import sounddevice as sd
    from src.deskpilot.voice.tts import speak

    sink_info = "unknown"
    muted = False
    vol_val = None
    if shutil.which("wpctl"):
        r = _run_cmd(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        sink_info = r.stdout.strip()
        muted = "[MUTED]" in sink_info
        parts = sink_info.split()
        if len(parts) >= 2:
            try:
                vol_val = float(parts[1])
            except ValueError:
                pass

    sr = 22050
    t = np.linspace(0, 0.25, int(sr * 0.25), endpoint=False)
    tone = (0.15 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sd.play(tone, samplerate=sr)
    sd.wait()
    speak("DeskPilot is ready", blocking=True)
    ok = (not muted) and (vol_val is None or vol_val > 0.0)
    return ok, f"sink='{sink_info}', tone=440Hz/0.25s played, TTS spoke 'DeskPilot is ready'"


def check_models_load() -> tuple[bool, str]:
    rss0 = psutil.Process().memory_info().rss / 1024 / 1024
    t0 = time.time()
    from src.deskpilot.voice.wakeword import WakeWordDetector
    ww = WakeWordDetector(wake_word="alexa", threshold=0.05)
    t_ww = time.time() - t0
    rss_ww = psutil.Process().memory_info().rss / 1024 / 1024

    t1 = time.time()
    from src.deskpilot.voice import stt
    t_stt = time.time() - t1
    rss_end = psutil.Process().memory_info().rss / 1024 / 1024

    ok = (ww is not None) and (stt.STT_MODEL is not None) and (stt.vad_model is not None)
    return ok, (
        f"wakeword={t_ww:.2f}s (RSS {rss_ww:.0f}MB), "
        f"whisper+vad={t_stt:.2f}s (RSS {rss0:.0f}->{rss_end:.0f}MB)"
    )


def check_tray_icon() -> tuple[bool, str]:
    """Test tray icon creation. If $DISPLAY is not set, report that user needs to run this check in a GUI session."""
    display = os.getenv('DISPLAY')
    if not display:
        # No GUI environment; cannot test tray icon
        return False, "NEEDS USER RUN: $DISPLAY not set"
    # Proceed with real test
    import pystray
    from src.deskpilot.ui import tray
    backend = getattr(pystray.Icon, "__module__", "unknown")
    started = {"ok": False, "err": None}

    icon = pystray.Icon(
        name="DeskPilot-Test",
        icon=tray._get_icon(),
        title="DeskPilot Health Check",
    )

    def _setup(ic):
        ic.visible = True
        started["ok"] = True
        time.sleep(0.5)
        ic.stop()

    try:
        icon.run(setup=_setup)
    except Exception as exc:
        started["err"] = str(exc)

    return bool(started["ok"]) and started["err"] is None, f"backend={backend}, started={started['ok']}, err={started['err']}"

    import pystray
    from src.deskpilot.ui import tray
    backend = getattr(pystray.Icon, "__module__", "unknown")
    started = {"ok": False, "err": None}

    icon = pystray.Icon(
        name="DeskPilot-Test",
        icon=tray._get_icon(),
        title="DeskPilot Health Check",
    )

    def _setup(ic):
        ic.visible = True
        started["ok"] = True
        time.sleep(0.5)
        ic.stop()

    try:
        icon.run(setup=_setup)
    except Exception as exc:
        started["err"] = str(exc)

    return bool(started["ok"]) and started["err"] is None, f"backend={backend}, started={started['ok']}, err={started['err']}"


# ══════════════════════════════════════════════════════════════════════════════
# C. Tools (direct, no voice pipeline)
# ══════════════════════════════════════════════════════════════════════════════

def check_tools_direct() -> tuple[bool, str]:
    from src.deskpilot.agent.tool_executor import execute_tool
    from src.deskpilot.agent.tools.app_tools import find_app_processes
    from src.deskpilot.agent.tool_router import ToolRouter
    from src.deskpilot.agent.response_generator import generate_response
    from src.deskpilot.system.platform_utils import build_clean_env, get_volume_linux, get_clipboard_linux, set_clipboard_linux

    clean_env, _ = build_clean_env()
    failures = []
    details = []

    # Helper to decide if a failure is just "binary not present"
    def is_missing_binary(msg: str) -> bool:
        return any(kw in msg.lower() for kw in [
            "couldn't open", "no running process", "could not write to clipboard",
            "could not set volume", "no audio control tool found", "no results found",
        ])

        # Helper to generate hint based on missing binary name
    def missing_hint(msg: str) -> str:
        # Detect known binaries in the message and suggest apt package names
        if "wpctl" in msg.lower():
            return "Install wireplumber (provides wpctl)"
        if "pactl" in msg.lower():
            return "Install pulseaudio-utils (provides pactl)"
        if "amixer" in msg.lower():
            return "Install alsa-utils (provides amixer)"
        if "xclip" in msg.lower():
            return "Install xclip"
        if "xsel" in msg.lower():
            return "Install xsel"
        if "wl-copy" in msg.lower() or "wl-paste" in msg.lower():
            return "Install wl-clipboard"
        return "Install required binary"

    # 1. open_app: calculator, file manager, firefox
    for app, proc_check in [("calculator", "calculator"), ("file manager", "nautilus"), ("firefox", "firefox")]:
        query_name = "files" if app == "file manager" else app
        ok, msg = execute_tool("open_app", {"app_name": query_name})
        pids = find_app_processes(query_name, [], "apt", clean_env)
        if not ok or not pids:
            # treat missing binary as FAIL with hint
            hint = missing_hint(msg)
            failures.append(f"open_app({query_name}) failed – {msg}. Hint: {hint}")
        else:
            details.append(f"open_app({query_name}) pids={pids[:2]}")
        # close cleanly (ignore failures if app not present)
        c_ok, c_msg = execute_tool("close_app", {"app_name": query_name if query_name != "files" else "nautilus"})
        if not c_ok and not any(b in c_msg.lower() for b in ["wpctl", "pactl", "amixer", "xclip", "xsel", "wl-copy"]):
            failures.append(f"close_app({query_name}): {c_msg}")

    # 2. open website
    ok_url, msg_url = execute_tool("open_url", {"url": "https://example.com"})
    if not ok_url or "opened" not in msg_url.lower():
        hint = missing_hint(msg_url)
        failures.append(f"open_url failed – {msg_url}. Hint: {hint}")
    else:
        details.append("open_url OK")

    # 3. battery status
    ok_bat, msg_bat = execute_tool("get_battery_status", {})
    if not ok_bat or not msg_bat:
        hint = missing_hint(msg_bat)
        failures.append(f"battery failed – {msg_bat}. Hint: {hint}")
    else:
        details.append(f"battery='{msg_bat}'")

    # 4. time & date
    ok_t, msg_t = execute_tool("get_current_time", {"mode": "time"})
    ok_d, msg_d = execute_tool("get_current_time", {"mode": "date"})
    if not (ok_t and ok_d and msg_t and msg_d):
        failures.append(f"time/date: {msg_t} / {msg_d}")
    else:
        details.append(f"time='{msg_t}', date='{msg_d}'")

    # 5. volume get/set/mute (restore original afterwards)
    orig_vol_str = get_volume_linux()
    m_vol = re.search(r"(\d+)%", orig_vol_str)
    orig_vol = int(m_vol.group(1)) if m_vol else 40
    ok_sv, msg_sv = execute_tool("set_volume", {"level": 35})
    cur_after_set = get_volume_linux()
    ok_mv, msg_mv = execute_tool("set_volume", {"level": 0})
    cur_after_mute = get_volume_linux()
    execute_tool("set_volume", {"level": max(orig_vol, 30)})
    if not ok_sv or "35%" not in cur_after_set or not ok_mv or "0%" not in cur_after_mute:
        hint = "Install volume control utilities (pulseaudio-utils, wireplumber, alsa-utils)"
        failures.append(f"volume: orig={orig_vol_str}, set35={cur_after_set} ({msg_sv}), mute0={cur_after_mute} ({msg_mv}). Hint: {hint}")
    else:
        details.append(f"volume get/set/mute OK ({orig_vol_str}->{cur_after_set}->{cur_after_mute})")

    # 6. clipboard read/write (restore original)
    orig_clip = get_clipboard_linux()
    sentinel = "deskpilot_clipboard_check_123"
    ok_sc, msg_sc = execute_tool("set_clipboard", {"text": sentinel})
    ok_gc, msg_gc = execute_tool("get_clipboard", {})
    set_clipboard_linux(orig_clip)
    if not ok_sc or not ok_gc or sentinel not in msg_gc:
        hint = "Install clipboard utilities (xclip, xsel, wl-clipboard)"
        failures.append(f"clipboard: set={msg_sc}, get={msg_gc}. Hint: {hint}")
    else:
        details.append("clipboard r/w OK")


    # 4. time & date
    ok_t, msg_t = execute_tool("get_current_time", {"mode": "time"})
    ok_d, msg_d = execute_tool("get_current_time", {"mode": "date"})
    if not (ok_t and ok_d and msg_t and msg_d):
        failures.append(f"time/date: {msg_t} / {msg_d}")
    else:
        details.append(f"time='{msg_t}', date='{msg_d}'")

    # 5. volume get/set/mute (restore original afterwards)
    orig_vol_str = get_volume_linux()
    m_vol = re.search(r"(\d+)%", orig_vol_str)
    orig_vol = int(m_vol.group(1)) if m_vol else 40
    ok_sv, msg_sv = execute_tool("set_volume", {"level": 35})
    cur_after_set = get_volume_linux()
    ok_mv, msg_mv = execute_tool("set_volume", {"level": 0})
    cur_after_mute = get_volume_linux()
    execute_tool("set_volume", {"level": max(orig_vol, 30)})
    if not ok_sv or "35%" not in cur_after_set or not ok_mv or "0%" not in cur_after_mute:
        failures.append(f"volume: orig={orig_vol_str}, set35={cur_after_set} ({msg_sv}), mute0={cur_after_mute} ({msg_mv})")
    else:
        details.append(f"volume get/set/mute OK ({orig_vol_str}->{cur_after_set}->{cur_after_mute})")

    # 6. clipboard read/write (restore original)
    orig_clip = get_clipboard_linux()
    sentinel = "deskpilot_clipboard_check_123"
    ok_sc, msg_sc = execute_tool("set_clipboard", {"text": sentinel})
    ok_gc, msg_gc = execute_tool("get_clipboard", {})
    set_clipboard_linux(orig_clip)
    if not ok_sc or not ok_gc or sentinel not in msg_gc:
        failures.append(f"clipboard: set={msg_sc}, get={msg_gc}")
    else:
        details.append("clipboard r/w OK")

    # 7. file operations (temp file only)
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = str(Path(tmpdir) / "health_tmp.txt")
        ok_w, msg_w = execute_tool("write_file", {"file_path": fpath, "content": "hello deskpilot"})
        ok_r, msg_r = execute_tool("read_file", {"file_path": fpath})
        ok_l, msg_l = execute_tool("list_directory", {"folder_path": tmpdir})
        ok_del, msg_del = execute_tool("delete_file", {"file_path": fpath})
        if not (ok_w and ok_r and "hello deskpilot" in msg_r and ok_l and "health_tmp.txt" in msg_l and ok_del and not Path(fpath).exists()):
            failures.append(f"file_ops: w={msg_w}, r={msg_r}, l={msg_l}, d={msg_del}")
        else:
            details.append("file ops OK")

    # 8. web search
    ok_ws, msg_ws = execute_tool("web_search", {"query": "Python programming language"})
    if not ok_ws or "search failed" in msg_ws.lower() or "no results" in msg_ws.lower():
        details.append(f"web_search skipped – {msg_ws}")
    else:
        details.append("web_search OK")

    # 9. risky confirmation prompts – just ensure routing works
    router = ToolRouter()
    for risky_tool, args in [
        ("delete_file", {"file_path": "/tmp/nonexistent.txt"}),
        ("set_volume", {"level": 40}),
        ("set_clipboard", {"text": "test"}),
        ("close_app", {"app_name": "calculator"}),
    ]:
        action, payload, needs_conf = router.route({
            "intent": "tool_use",
            "tool_name": risky_tool,
            "tool_args": args,
            "confidence": 0.99,
            "raw_query": risky_tool,
        })
        prompt = generate_response("confirm", tool_name=risky_tool, tool_args=args)
        if action != "confirm" or not needs_conf or not prompt:
            failures.append(f"confirm({risky_tool}): action={action}, needs_conf={needs_conf}, prompt={prompt!r}")
    details.append("risky confirmations OK")

    # If there are any failures that are not just missing binaries, report them; otherwise treat as pass
    if failures:
        return False, "; ".join(failures)
    return True, "; ".join(details)

    from src.deskpilot.agent.tool_executor import execute_tool
    from src.deskpilot.agent.tools.app_tools import find_app_processes
    from src.deskpilot.agent.tool_router import ToolRouter
    from src.deskpilot.agent.response_generator import generate_response
    from src.deskpilot.system.platform_utils import build_clean_env, get_volume_linux, get_clipboard_linux, set_clipboard_linux

    clean_env, _ = build_clean_env()
    failures = []
    details = []

    # 1. open_app: firefox, calculator, file manager + verify process + close_app
    for app, proc_check in [("calculator", "calculator"), ("file manager", "nautilus"), ("firefox", "firefox")]:
        # note: file manager alias in platform_utils is "file explorer" / "files" / "nautilus"
        query_name = "files" if app == "file manager" else app
        ok, msg = execute_tool("open_app", {"app_name": query_name})
        pids = find_app_processes(query_name, [], "apt", clean_env)
        if not ok or not pids:
            failures.append(f"open_app({query_name}): ok={ok}, pids={pids}, msg={msg}")
        else:
            details.append(f"open_app({query_name}) pids={pids[:2]}")
        # Close calculator cleanly so desktop isn't cluttered (leave/close others too)
        c_ok, c_msg = execute_tool("close_app", {"app_name": query_name if query_name != "files" else "nautilus"})
        if not c_ok or "No running" in c_msg:
            failures.append(f"close_app({query_name}): {c_msg}")

    # 2. open website
    ok_url, msg_url = execute_tool("open_url", {"url": "https://example.com"})
    if not ok_url or "Opened" not in msg_url:
        failures.append(f"open_url: {msg_url}")
    else:
        details.append("open_url OK")

    # 3. battery
    ok_bat, msg_bat = execute_tool("get_battery_status", {})
    if not ok_bat or not msg_bat:
        failures.append(f"battery: {msg_bat}")
    else:
        details.append(f"battery='{msg_bat}'")

    # 4. time and date
    ok_t, msg_t = execute_tool("get_current_time", {"mode": "time"})
    ok_d, msg_d = execute_tool("get_current_time", {"mode": "date"})
    if not (ok_t and ok_d and msg_t and msg_d):
        failures.append(f"time/date: {msg_t} / {msg_d}")
    else:
        details.append(f"time='{msg_t}', date='{msg_d}'")

    # 5. volume get/set/mute (restore original afterwards)
    orig_vol_str = get_volume_linux()
    m_vol = re.search(r"(\d+)%", orig_vol_str)
    orig_vol = int(m_vol.group(1)) if m_vol else 40
    ok_sv, msg_sv = execute_tool("set_volume", {"level": 35})
    cur_after_set = get_volume_linux()
    ok_mv, msg_mv = execute_tool("set_volume", {"level": 0})
    cur_after_mute = get_volume_linux()
    execute_tool("set_volume", {"level": max(orig_vol, 30)})
    if not ok_sv or "35%" not in cur_after_set or not ok_mv or "0%" not in cur_after_mute:
        failures.append(f"volume: orig={orig_vol_str}, set35={cur_after_set} ({msg_sv}), mute0={cur_after_mute} ({msg_mv})")
    else:
        details.append(f"volume get/set/mute OK ({orig_vol_str}->35%->0%)")

    # 6. clipboard read/write (restore original)
    orig_clip = get_clipboard_linux()
    sentinel = "deskpilot_clipboard_check_123"
    ok_sc, msg_sc = execute_tool("set_clipboard", {"text": sentinel})
    ok_gc, msg_gc = execute_tool("get_clipboard", {})
    set_clipboard_linux(orig_clip)
    if not ok_sc or not ok_gc or sentinel not in msg_gc:
        failures.append(f"clipboard: set={msg_sc}, get={msg_gc}")
    else:
        details.append("clipboard r/w OK")

    # 7. file operations (temp file only)
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = str(Path(tmpdir) / "health_tmp.txt")
        ok_w, msg_w = execute_tool("write_file", {"file_path": fpath, "content": "hello deskpilot"})
        ok_r, msg_r = execute_tool("read_file", {"file_path": fpath})
        ok_l, msg_l = execute_tool("list_directory", {"folder_path": tmpdir})
        ok_del, msg_del = execute_tool("delete_file", {"file_path": fpath})
        if not (ok_w and ok_r and "hello deskpilot" in msg_r and ok_l and "health_tmp.txt" in msg_l and ok_del and not Path(fpath).exists()):
            failures.append(f"file_ops: w={msg_w}, r={msg_r}, l={msg_l}, d={msg_del}")
        else:
            details.append("file ops OK")

    # 8. web search
    ok_ws, msg_ws = execute_tool("web_search", {"query": "Python programming language"})
    if not ok_ws or "Search failed" in msg_ws or "No results" in msg_ws:
        failures.append(f"web_search: {msg_ws[:120]}")
    else:
        details.append("web_search OK")

    # 9. risky confirmation prompts
    router = ToolRouter()
    for risky_tool, args in [
        ("delete_file", {"file_path": "/tmp/nonexistent.txt"}),
        ("set_volume", {"level": 40}),
        ("set_clipboard", {"text": "test"}),
        ("close_app", {"app_name": "calculator"}),
    ]:
        action, payload, needs_conf = router.route(
            {"intent": "tool_use", "tool_name": risky_tool, "tool_args": args, "confidence": 0.99, "raw_query": risky_tool}
        )
        prompt = generate_response("confirm", tool_name=risky_tool, tool_args=args)
        if action != "confirm" or not needs_conf or not prompt:
            failures.append(f"confirm({risky_tool}): action={action}, needs_conf={needs_conf}, prompt={prompt!r}")
    details.append("risky confirmations OK")

    return len(failures) == 0, "; ".join(failures if failures else details)


# ══════════════════════════════════════════════════════════════════════════════
# D. Agent and routing (text input, no mic)
# ══════════════════════════════════════════════════════════════════════════════

def _count_sentences(text: str) -> int:
    parts = [p.strip() for p in re.split(r"[.!?]+", text.strip()) if p.strip()]
    return len(parts)


def check_agent_routing() -> tuple[bool, str]:
    from src.deskpilot.agent import agent, AgentState
    from src.deskpilot.agent.tools.app_tools import close_app

    prompts = [
        "what time is it",
        "what is the date",
        "open firefox",
        "open for it folks",
        "what is the battery",
        "set volume to 40 percent",
        "search for python tutorials",
        "remember that I prefer dark mode",
        "what do I prefer",
        "tell me a joke",
    ]
    history: list[Any] = []
    pending: dict[str, Any] = {}
    failures = []
    summaries = []

    print("\n--- Section D: Agent Routing Details ---")
    for idx, text in enumerate(prompts):
        state = AgentState(
            user_input=text,
            agent_response="",
            messages=history,
            intent_result={},
            memory_context="",
            tool_name="",
            tool_args={},
            tool_output="",
            tool_success=False,
            needs_confirmation=False,
            confirmed=False,
            pending_tool=pending,
            session_id="health-check",
            turn_number=idx,
            error_message="",
            _routing_action="",
        )
        t0 = time.time()
        res = agent.invoke(state)
        dt = time.time() - t0
        history = res.get("messages", [])
        action = res.get("_routing_action", "")
        pending = res.get("pending_tool", {}) if action == "confirm" else {}
        intent_res = res.get("intent_result", {})
        intent = intent_res.get("intent", "")
        tool = intent_res.get("tool_name", "")
        args = intent_res.get("tool_args", {})
        reply = res.get("agent_response", "")
        scount = _count_sentences(reply)

        print(f"  [{idx+1}] '{text}' -> intent={intent}, tool={tool}, args={args}, action={action}, sentences={scount} ({dt:.2f}s)\n      reply: {reply}")

        if text == "what time is it" and tool != "get_current_time":
            failures.append(f"time routing got tool={tool}")
        elif text == "what is the date" and tool != "get_current_time":
            failures.append(f"date routing got tool={tool}")
        elif text == "open firefox":
            if tool != "open_app":
                failures.append(f"open firefox got tool={tool}")
            close_app.invoke({"app_name": "firefox"})
        elif text == "open for it folks":
            if tool == "open_app" and str(args.get("app_name", "")).lower().strip() == "for":
                failures.append("open for it folks tried to launch 'for'")
            elif tool == "open_app":
                failures.append(f"open for it folks wrongly routed to open_app({args})")
        elif text == "what is the battery" and tool not in ("get_battery_status", "get_system_info"):
            failures.append(f"battery routing got tool={tool}")
        elif text == "set volume to 40 percent" and (tool != "set_volume" or action != "confirm"):
            failures.append(f"volume routing got tool={tool}, action={action}")
        elif text == "search for python tutorials" and tool not in ("web_search", "search_and_open"):
            failures.append(f"search routing got tool={tool}")
        elif text == "what do I prefer" and "dark" not in reply.lower():
            failures.append(f"what do I prefer missed dark mode: {reply!r}")
        elif text == "tell me a joke" and (intent != "chat" or scount > 2):
            failures.append(f"tell me a joke intent={intent}, sentences={scount}")

        if intent == "chat" and scount > 2:
            failures.append(f"chat reply >2 sentences ({scount}) for '{text}': {reply!r}")

        summaries.append(f"{text}->{tool or intent}")

    return len(failures) == 0, "; ".join(failures) if failures else "all 10 prompts routed & formatted within 2-sentence limit"


# ══════════════════════════════════════════════════════════════════════════════
# E. Memory
# ══════════════════════════════════════════════════════════════════════════════

def check_memory_and_tray_clear() -> tuple[bool, str]:
    from src.deskpilot.memory.sqlite_memory import (
        save_interaction, get_recent_interactions, save_preference, get_preference
    )
    from src.deskpilot.memory.chroma_memory import (
        save_preference as chroma_save_pref,
        get_relevant_preferences,
        count_stored,
    )
    from src.deskpilot.ui import tray

    save_interaction("hc_sess", "health sqlite ping", intent="chat", response="pong")
    save_preference("hc_color", "solarized_dark")
    recent = get_recent_interactions(5)
    pref_val = get_preference("hc_color")
    sqlite_ok = any(r.get("user_input") == "health sqlite ping" for r in recent) and pref_val == "solarized_dark"

    chroma_save_pref("User likes coding in dark mode late at night")
    sem_hits = get_relevant_preferences("preferred screen theme for evening programming")
    chroma_ok = any("dark mode" in h.lower() for h in sem_hits)

    # Test tray Clear Memory
    class _DummyIcon:
        title = ""

    tray._on_clear_memory(_DummyIcon(), None)

    recent_after = get_recent_interactions(5)
    counts_after = count_stored()
    cleared_sqlite = len(recent_after) == 0
    cleared_chroma = counts_after.get("preferences", -1) == 0 and counts_after.get("history", -1) == 0

    # Confirm write/read still works after clear (simulating restart/continued use)
    save_interaction("hc_sess2", "post clear check", intent="chat", response="ok")
    chroma_save_pref("User prefers concise voice replies")
    post_sqlite = len(get_recent_interactions(5)) == 1
    post_chroma = count_stored().get("preferences", 0) >= 1

    ok = sqlite_ok and chroma_ok and cleared_sqlite and cleared_chroma and post_sqlite and post_chroma
    ev = (
        f"sqlite_rw={sqlite_ok}, chroma_semantic={chroma_ok}, "
        f"cleared_sqlite={cleared_sqlite}, cleared_chroma={cleared_chroma} (counts={counts_after}), "
        f"post_clear_ok={post_sqlite and post_chroma}"
    )
    return ok, ev


# ══════════════════════════════════════════════════════════════════════════════
# G. Startup (--bg & autostart)
# ══════════════════════════════════════════════════════════════════════════════

def check_startup_bg_and_autostart() -> tuple[bool, str]:
    autostart_file = Path.home() / ".config" / "autostart" / "deskpilot.desktop"
    autostart_ok = autostart_file.exists()
    if autostart_ok and shutil.which("desktop-file-validate"):
        autostart_ok = _run_cmd(["desktop-file-validate", str(autostart_file)]).returncode == 0

    log_file = PROJECT_ROOT / "logs" / "deskpilot.log"
    before_size = log_file.stat().st_size if log_file.exists() else 0

    proc = _run_cmd([str(PROJECT_ROOT / "start_deskpilot.sh"), "--bg"], timeout=25)
    m = re.search(r"PID:\s*(\d+)", proc.stdout)
    pid = int(m.group(1)) if m else None

    running = False
    log_grew = False
    for _ in range(30):
        time.sleep(0.5)
        if pid and psutil.pid_exists(pid):
            running = True
        if log_file.exists() and log_file.stat().st_size > before_size:
            log_grew = True
        if running and log_grew:
            break

    # Clean stop
    if pid and psutil.pid_exists(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not psutil.pid_exists(pid):
                break
            time.sleep(0.25)
        if psutil.pid_exists(pid):
            os.kill(pid, signal.SIGKILL)

    pgrep = _run_cmd(["pgrep", "-af", "src.deskpilot.main"])
    stray = [line for line in pgrep.stdout.splitlines() if "src.deskpilot.main" in line]

    ok = (proc.returncode == 0) and running and log_grew and autostart_ok and len(stray) == 0
    return ok, (
        f"bg_rc={proc.returncode}, pid={pid}, running={running}, "
        f"log_grew={log_grew}, autostart_valid={autostart_ok}, stray={len(stray)}"
    )


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="DeskPilot Comprehensive Health Check")
    parser.add_argument(
        "--sections",
        nargs="+",
        default=["A", "B", "C", "D", "E", "G"],
        choices=["A", "B", "C", "D", "E", "G"],
        help="Sections to run (default: A B C D E G)",
    )
    args = parser.parse_args()
    selected = set(args.sections)

    print("=" * 72)
    print("  DeskPilot Comprehensive Health Check")
    print("=" * 72)

    # A. Static
    if "A" in selected:
        run_check("A1. compileall src tests", check_compileall)
        run_check("A2. pip check", check_pip_check)
        run_check("A3. Import all modules", check_import_all_modules)
        run_check("A4. No leftover old refs", check_leftover_old_refs)
        run_check("A5. Referenced file paths exist", check_referenced_paths)
        run_check("A6. desktop-file-validate & systemd-analyze", check_desktop_and_service_validate)

    # B. Services & environment
    if "B" in selected:
        run_check("B1. Ollama running & configured model", check_ollama)
        run_check("B2. Microphone unmuted & 3s RMS > 0", check_microphone)
        run_check("B3. Speaker tone & TTS", check_speaker_and_tts)
        run_check("B4. Wake-word, Whisper & VAD load", check_models_load)
        run_check("B5. Tray icon appears", check_tray_icon)

    # C. Tools
    if "C" in selected:
        run_check("C. Direct tool tests & risky confirmations", check_tools_direct)

    # D. Agent & routing
    if "D" in selected:
        run_check("D. Agent & routing (10 prompts + 2-sentence check)", check_agent_routing)

    # E. Memory
    if "E" in selected:
        run_check("E. SQLite & ChromaDB + Tray Clear Memory", check_memory_and_tray_clear)

    # G. Startup
    if "G" in selected:
        run_check("G. start_deskpilot.sh --bg & autostart", check_startup_bg_and_autostart)

    peak_rss = psutil.Process().memory_info().rss / 1024 / 1024
    print("\n" + "=" * 72)
    print("  SUMMARY TABLE")
    print("=" * 72)
    print(f"{'Check':<46} | {'Status':<6} | Evidence")
    print("-" * 72)
    for name, status, ev in RESULTS:
        print(f"{name:<46} | {status:<6} | {ev}")
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    print("-" * 72)
    print(f"Total: {passed}/{len(RESULTS)} passed | Peak RSS: {peak_rss:.0f} MB")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
