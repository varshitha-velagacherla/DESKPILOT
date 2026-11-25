"""
app_tools.py — Linux application launching, verification, and management.

Launches desktop apps in a sanitized environment (preserving GNOME/Snap/Wayland/X11/DBus
session variables while removing Conda/.venv/LD_LIBRARY_PATH contamination), follows the
fallback launch order (app map -> gtk-launch -> xdg-open), redirects stdout/stderr to
logs/apps.log with start_new_session=True, and verifies process/window creation.
"""

import logging
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

import psutil
from langchain_core.tools import tool

from src.deskpilot.system.platform_utils import (
    build_clean_env,
    build_launch_plan,
    detect_session_type,
)

logger = logging.getLogger("deskpilot.tools.app")

APPS_LOG_PATH = Path("logs/apps.log")
LAUNCH_VERIFY_INITIAL_DELAY_S = 1.5
LAUNCH_VERIFY_POLL_STEP_S = 0.5
LAUNCH_VERIFY_MAX_WAIT_S = 3.5

APP_VERIFY_TARGETS: dict[str, dict[str, Any]] = {
    "firefox": {
        "proc_patterns": ["firefox", "firefox-bin"],
        "window_keywords": ["firefox", "mozilla firefox"],
    },
    "chrome": {
        "proc_patterns": ["chrome", "google-chrome", "chromium"],
        "window_keywords": ["chrome", "chromium"],
    },
    "google chrome": {
        "proc_patterns": ["chrome", "google-chrome", "chromium"],
        "window_keywords": ["chrome", "chromium"],
    },
    "chromium": {
        "proc_patterns": ["chromium", "chromium-browser"],
        "window_keywords": ["chromium"],
    },
    "calculator": {
        "proc_patterns": ["gnome-calculator", "kcalc", "qalculate"],
        "window_keywords": ["calculator"],
    },
    "gnome-calculator": {
        "proc_patterns": ["gnome-calculator"],
        "window_keywords": ["calculator"],
    },
    "terminal": {
        "proc_patterns": ["gnome-terminal-server", "gnome-terminal", "konsole", "xterm", "tilix", "alacritty"],
        "window_keywords": ["terminal"],
    },
    "gnome-terminal": {
        "proc_patterns": ["gnome-terminal-server", "gnome-terminal"],
        "window_keywords": ["terminal"],
    },
    "vscode": {
        "proc_patterns": ["code", "codium"],
        "window_keywords": ["visual studio code", "code"],
    },
    "vs code": {
        "proc_patterns": ["code", "codium"],
        "window_keywords": ["visual studio code", "code"],
    },
    "visual studio code": {
        "proc_patterns": ["code", "codium"],
        "window_keywords": ["visual studio code", "code"],
    },
    "code": {
        "proc_patterns": ["code"],
        "window_keywords": ["visual studio code", "code"],
    },
    "nautilus": {
        "proc_patterns": ["nautilus"],
        "window_keywords": ["files", "nautilus"],
    },
    "files": {
        "proc_patterns": ["nautilus", "nemo", "thunar"],
        "window_keywords": ["files", "nautilus", "nemo", "thunar"],
    },
    "file explorer": {
        "proc_patterns": ["nautilus", "nemo", "thunar", "dolphin"],
        "window_keywords": ["files", "nautilus", "nemo", "thunar", "dolphin"],
    },
}

_WRAPPER_BINARIES = {"gtk-launch", "xdg-open", "sh", "bash", "dash", "pgrep", "wmctrl"}
_TEST_RUNNER_TOKENS = ("pytest", "unittest", "test_open_app")


def _write_apps_log(line: str) -> None:
    """Append a timestamped diagnostic line to logs/apps.log."""
    APPS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(APPS_LOG_PATH, "a", encoding="utf-8", errors="replace") as fh:
        fh.write(f"[{ts}] {line}\n")


def _read_log_slice(offset: int) -> str:
    """Read newly written child output/stderr from logs/apps.log after offset."""
    try:
        if not APPS_LOG_PATH.exists():
            return ""
        with open(APPS_LOG_PATH, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            return fh.read().strip()
    except OSError:
        return ""


def _ancestor_pids() -> set[int]:
    """Return PIDs of current process and its ancestors to avoid self-matching."""
    pids = {os.getpid()}
    try:
        proc = psutil.Process(os.getpid())
        for parent in proc.parents():
            pids.add(parent.pid)
    except Exception:
        pass
    return pids


def _is_launcher_wrapper_process(
    name: str,
    exe: str,
    cmdline: list[str],
    launcher_pid: Optional[int] = None,
    launcher_is_wrapper: bool = False,
    pid: Optional[int] = None,
) -> bool:
    """Return True if process is a launcher/wrapper rather than the target GUI app."""
    if launcher_is_wrapper and launcher_pid is not None and pid == launcher_pid:
        return True

    lname = (name or "").lower()
    exe_base = os.path.basename(exe or "").lower()
    if lname in _WRAPPER_BINARIES or exe_base in _WRAPPER_BINARIES:
        return True

    cmd_joined = " ".join(cmdline).lower()
    if any(tok in cmd_joined for tok in _TEST_RUNNER_TOKENS):
        return True

    # Snap / flatpak launcher commands before the real app process spawns
    if exe_base == "snap" or lname == "snap":
        return True
    if cmdline and os.path.basename(cmdline[0]).lower() == "snap" and "run" in cmdline[1:3]:
        return True
    if cmdline and cmdline[0].startswith("/snap/bin/"):
        return True
    if cmdline and os.path.basename(cmdline[0]).lower() == "flatpak" and "run" in cmdline[1:3]:
        return True

    return False


def _target_patterns(app_name: str, cmd_parts: list[str]) -> tuple[list[str], list[str]]:
    """Return (process_patterns, window_keywords) for an app."""
    key = app_name.lower().strip()
    entry = APP_VERIFY_TARGETS.get(key)
    if entry:
        return list(entry["proc_patterns"]), list(entry["window_keywords"])

    patterns = []
    if key and not key.startswith(("http://", "https://")):
        patterns.append(key)
    if cmd_parts:
        base = os.path.basename(cmd_parts[0]).lower()
        if base not in _WRAPPER_BINARIES and base not in ("snap", "flatpak") and base not in patterns:
            patterns.append(base)
    return patterns or [key], patterns or [key]


def _pgrep_pids(pattern: str, clean_env: Mapping[str, str]) -> set[int]:
    """Query matching PIDs with pgrep -f when available."""
    pgrep_path = shutil.which("pgrep", path=clean_env.get("PATH"))
    if not pgrep_path or not pattern:
        return set()
    try:
        res = subprocess.run(
            [pgrep_path, "-f", pattern],
            env=dict(clean_env),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode != 0:
            return set()
        return {int(line.strip()) for line in res.stdout.splitlines() if line.strip().isdigit()}
    except Exception:
        return set()


def find_app_processes(
    app_name: str,
    cmd_parts: list[str],
    install_type: str,
    clean_env: Mapping[str, str],
    launcher_pid: Optional[int] = None,
    launcher_is_wrapper: bool = False,
) -> list[int]:
    """
    Independently verify whether actual target application processes exist.
    Uses pgrep -f plus psutil inspection, excluding launcher wrappers and test runners.
    """
    patterns, _ = _target_patterns(app_name, cmd_parts)
    excluded_pids = _ancestor_pids()

    candidate_pids: set[int] = set()
    for pat in patterns:
        candidate_pids.update(_pgrep_pids(pat, clean_env))

    matched_pids: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "status"]):
        try:
            pid = proc.info["pid"]
            if pid in excluded_pids:
                continue
            if proc.info.get("status") == psutil.STATUS_ZOMBIE:
                continue

            name = proc.info.get("name") or ""
            exe = proc.info.get("exe") or ""
            cmdline = proc.info.get("cmdline") or []
            if _is_launcher_wrapper_process(
                name=name,
                exe=exe,
                cmdline=cmdline,
                launcher_pid=launcher_pid,
                launcher_is_wrapper=launcher_is_wrapper,
                pid=pid,
            ):
                continue

            haystack = " ".join([name, exe, " ".join(cmdline)]).lower()
            matches_pattern = any(pat.lower() in haystack for pat in patterns)
            if not matches_pattern and pid not in candidate_pids:
                continue
            if not matches_pattern:
                continue

            # For snap apps, prefer actual snap runtime path or binary name
            if install_type == "snap" and patterns and not (
                f"/snap/{patterns[0]}" in haystack or name.lower() in patterns
            ):
                # Still accept if process name or exe matches pattern cleanly
                if not any(pat in name.lower() or pat in os.path.basename(exe).lower() for pat in patterns):
                    continue

            matched_pids.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return sorted(set(matched_pids))


def list_wmctrl_windows(clean_env: Mapping[str, str]) -> Optional[dict[str, str]]:
    """
    Return {window_id: title} from wmctrl -l on X11, or None if unavailable/Wayland.
    """
    if detect_session_type(clean_env) != "x11":
        return None
    wmctrl_path = shutil.which("wmctrl", path=clean_env.get("PATH"))
    if not wmctrl_path:
        return None
    try:
        res = subprocess.run(
            [wmctrl_path, "-l"],
            env=dict(clean_env),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode != 0:
            return None
        windows: dict[str, str] = {}
        for line in res.stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 4:
                windows[parts[0]] = parts[3].strip()
        return windows
    except Exception:
        return None


def _check_window_opened(
    app_name: str,
    cmd_parts: list[str],
    baseline_windows: Optional[dict[str, str]],
    clean_env: Mapping[str, str],
) -> Optional[bool]:
    """
    Check X11 windows via wmctrl -l.
    Returns True/False on X11 when wmctrl works, or None when unavailable (e.g. Wayland).
    """
    current_windows = list_wmctrl_windows(clean_env)
    if current_windows is None:
        return None

    if baseline_windows is not None:
        new_ids = set(current_windows) - set(baseline_windows)
        if new_ids:
            return True

    _, window_keywords = _target_patterns(app_name, cmd_parts)
    for title in current_windows.values():
        lower_title = title.lower()
        if any(kw in lower_title for kw in window_keywords):
            return True
    return False


def _is_launcher_command(strategy: str, cmd_parts: list[str], install_type: str) -> bool:
    """Return True if the spawned Popen command is a wrapper/forwarder rather than the app binary."""
    if strategy in ("gtk-launch", "xdg-open"):
        return True
    if install_type in ("snap", "flatpak"):
        return True
    exe_base = os.path.basename(cmd_parts[0]).lower() if cmd_parts else ""
    return exe_base in _WRAPPER_BINARIES or exe_base in ("snap", "flatpak")


def launch_app(app_name: str) -> tuple[bool, str]:
    """
    Launch an application with a clean environment, detached session, and independent verification.
    Returns (success, spoken_message).
    """
    display_name = app_name.strip()
    if not display_name:
        return False, "I couldn't open that application."

    clean_env, env_diff = build_clean_env()
    session_type = detect_session_type(clean_env)
    plan = build_launch_plan(display_name, clean_env)

    if not plan:
        msg = f"I couldn't open {display_name}."
        _write_apps_log(
            f"FAILED app='{display_name}' reason='no launch candidate resolved' "
            f"session={session_type} env_diff={env_diff}"
        )
        logger.warning(f"[app] {msg} (no candidate found)")
        return False, msg

    last_error = ""
    for candidate in plan:
        strategy = candidate["strategy"]
        cmd_parts = candidate["cmd_parts"]
        resolved_path = candidate["resolved_path"]
        install_type = candidate["install_type"]
        desktop_id = candidate.get("desktop_id")
        launcher_is_wrapper = _is_launcher_command(strategy, cmd_parts, install_type)

        baseline_windows = list_wmctrl_windows(clean_env)
        baseline_pids = set(
            find_app_processes(
                display_name,
                cmd_parts,
                install_type,
                clean_env,
                launcher_is_wrapper=launcher_is_wrapper,
            )
        )

        _write_apps_log(
            f"LAUNCH app='{display_name}' strategy={strategy} install_type={install_type} "
            f"cmd={cmd_parts} resolved_path='{resolved_path}' desktop_id={desktop_id} "
            f"session={session_type} env_diff={env_diff}"
        )
        logger.info(
            f"[app] launching '{display_name}' | strategy={strategy} | "
            f"cmd={cmd_parts} | resolved='{resolved_path}' | env_diff={env_diff}"
        )

        APPS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log_offset = APPS_LOG_PATH.stat().st_size if APPS_LOG_PATH.exists() else 0

        try:
            with open(APPS_LOG_PATH, "a", encoding="utf-8", errors="replace") as log_fh:
                proc = subprocess.Popen(
                    cmd_parts,
                    env=clean_env,
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=log_fh,
                    stderr=log_fh,
                )
        except Exception as e:
            last_error = str(e)
            _write_apps_log(
                f"LAUNCH_ERROR app='{display_name}' cmd={cmd_parts} error='{e}'"
            )
            logger.error(f"[app] Popen failed for {cmd_parts}: {e}")
            continue

        # Wait ~1.5s then inspect exit code, running application processes, and visible windows
        time.sleep(LAUNCH_VERIFY_INITIAL_DELAY_S)
        deadline = time.monotonic() + max(0.0, LAUNCH_VERIFY_MAX_WAIT_S - LAUNCH_VERIFY_INITIAL_DELAY_S)

        rc = proc.poll()
        app_pids: list[int] = []
        window_found: Optional[bool] = None
        verified = False

        while True:
            rc = proc.poll()
            if rc is not None and rc != 0:
                break

            child_output = _read_log_slice(log_offset)
            lower_output = child_output.lower()
            if any(
                err in lower_output
                for err in ("failed to open display", "cannot open display", "unable to init server")
            ):
                # Give failing GUI process a moment to finish exiting so we capture its exit code
                time.sleep(0.3)
                rc = proc.poll()
                verified = False
                break

            launcher_alive = rc is None
            app_pids = find_app_processes(
                display_name,
                cmd_parts,
                install_type,
                clean_env,
                launcher_pid=proc.pid,
                launcher_is_wrapper=launcher_is_wrapper,
            )
            new_app_pids = [p for p in app_pids if p not in baseline_pids]
            window_found = _check_window_opened(
                display_name, cmd_parts, baseline_windows, clean_env
            )

            # Never treat Popen.poll() == None alone as proof; verify process or window independently.
            candidate_ok = False
            if strategy == "xdg-open":
                candidate_ok = window_found is True or (rc == 0 and bool(app_pids))
            elif window_found is True:
                candidate_ok = True
            elif window_found is None:
                # Wayland / wmctrl unavailable: require verified target app process
                candidate_ok = bool(app_pids)
            else:
                # X11 where wmctrl returned False (no matching/new window yet):
                # Accept if a new app process started (or existing single-instance process when rc==0)
                candidate_ok = bool(new_app_pids) or (rc == 0 and bool(app_pids))

            if candidate_ok:
                # Brief settle check for direct binaries so a late GTK/display init crash isn't missed
                if not launcher_is_wrapper and rc is None and window_found is None:
                    time.sleep(0.3)
                    rc = proc.poll()
                    child_output = _read_log_slice(log_offset)
                    lower_output = child_output.lower()
                    if (rc is not None and rc != 0) or any(
                        err in lower_output
                        for err in ("failed to open display", "cannot open display", "unable to init server")
                    ):
                        verified = False
                        break
                verified = True
                break

            if time.monotonic() >= deadline:
                break
            time.sleep(LAUNCH_VERIFY_POLL_STEP_S)

        child_output = _read_log_slice(log_offset)
        launcher_alive = rc is None

        if rc is not None and rc != 0:
            last_error = f"exit_code={rc}"
            _write_apps_log(
                f"FAILED app='{display_name}' cmd={cmd_parts} resolved_path='{resolved_path}' "
                f"pid={proc.pid} exit_code={rc} launcher_alive={launcher_alive} "
                f"app_pids={app_pids} window_found={window_found} stderr={child_output!r}"
            )
            logger.error(
                f"[app] launch failed for '{display_name}' | cmd={cmd_parts} | "
                f"exit_code={rc} | stderr={child_output!r}"
            )
            continue

        if verified:
            _write_apps_log(
                f"SUCCESS app='{display_name}' cmd={cmd_parts} resolved_path='{resolved_path}' "
                f"pid={proc.pid} exit_code={rc} launcher_alive={launcher_alive} "
                f"app_process_found={bool(app_pids)} app_pids={app_pids} window_found={window_found}"
            )
            logger.info(
                f"[app] opened '{display_name}' | cmd={cmd_parts} | exit_code={rc} | "
                f"app_pids={app_pids} | window_found={window_found}"
            )
            return True, f"Opened {display_name} successfully."

        last_error = "no verified application process or window"
        _write_apps_log(
            f"FAILED app='{display_name}' cmd={cmd_parts} resolved_path='{resolved_path}' "
            f"pid={proc.pid} exit_code={rc} launcher_alive={launcher_alive} "
            f"app_process_found={bool(app_pids)} app_pids={app_pids} "
            f"window_found={window_found} reason='{last_error}' stderr={child_output!r}"
        )
        logger.warning(
            f"[app] verification failed for '{display_name}' | cmd={cmd_parts} | "
            f"exit_code={rc} | launcher_alive={launcher_alive} | app_pids={app_pids} | "
            f"window_found={window_found}"
        )

    msg = f"I couldn't open {display_name}."
    logger.error(f"[app] all candidates failed for '{display_name}': {last_error}")
    return False, msg


@tool
def open_app(app_name: str) -> str:
    """Open an application by name. Examples: firefox, chrome, vscode, calculator, nautilus."""
    _, message = launch_app(app_name)
    return message


@tool
def close_app(app_name: str) -> str:
    """Close a running application by name. Example: close firefox, close chrome."""
    key = app_name.lower().strip()
    # Normalize common aliases
    aliases = {
        "chrome": ["chrome", "google-chrome", "chromium"],
        "vscode": ["code", "code-oss"],
        "vs code": ["code", "code-oss"],
        "firefox": ["firefox"],
        "terminal": ["gnome-terminal", "konsole", "xterm"],
    }
    names_to_kill = aliases.get(key, [key])

    killed = []
    for proc in psutil.process_iter(["name", "pid"]):
        pname = (proc.info.get("name") or "").lower()
        if any(n in pname or pname in n for n in names_to_kill):
            try:
                proc.terminate()
                killed.append(proc.info["name"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    if killed:
        return f"Closed: {', '.join(set(killed))}"
    return f"No running process found for '{app_name}'"


@tool
def list_running_apps() -> str:
    """List all currently running applications (visible windows only)."""
    clean_env, _ = build_clean_env()
    session_type = detect_session_type(clean_env)

    # Try wmctrl on X11; on Wayland this usually fails
    if shutil.which("wmctrl", path=clean_env.get("PATH")) and session_type == "x11":
        try:
            out = subprocess.check_output(
                ["wmctrl", "-l"], env=clean_env, stderr=subprocess.DEVNULL, timeout=3
            ).decode()
            titles = []
            for line in out.strip().splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    title = parts[3].strip()
                    if title and title != "N/A":
                        titles.append(title)
            if titles:
                return "Open windows: " + ", ".join(titles[:15])
        except Exception as e:
            logger.debug(f"wmctrl failed: {e}")

    # Wayland / fallback: psutil
    procs = set()
    for p in psutil.process_iter(["name"]):
        try:
            name = p.info.get("name", "")
            if name and not name.startswith("["):
                procs.add(name)
        except Exception:
            pass

    if session_type == "wayland":
        note = " (Wayland: window titles unavailable; showing process names)"
    else:
        note = ""
    return f"Running processes{note}: " + ", ".join(sorted(procs)[:20])
