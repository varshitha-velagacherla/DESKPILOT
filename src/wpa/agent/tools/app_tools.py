"""
app_tools.py — Linux port

Changes from Windows version:
  - Removed Windows APP_MAP (.exe names)  
  - Removed import pygetwindow
  - open_app: uses platform_utils.resolve_app_command() + shutil.which()
  - close_app: uses psutil (cross-platform, unchanged)
  - list_running_apps: tries wmctrl -l (X11), falls back to psutil
"""

import subprocess
import shutil
import psutil
import logging
from langchain_core.tools import tool

from src.wpa.system.platform_utils import resolve_app_command, SESSION_TYPE

logger = logging.getLogger("wpa.tools.app")


@tool
def open_app(app_name: str) -> str:
    """Open an application by name. Examples: firefox, chrome, vscode, calculator, nautilus."""
    key = app_name.lower().strip()
    cmd = resolve_app_command(key)

    if cmd is None:
        return (
            f"Could not find '{app_name}' on this system. "
            f"Try installing it or use a website instead."
        )

    try:
        # Split multi-word commands like "libreoffice --writer"
        parts = cmd.split()
        subprocess.Popen(parts, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Opened {app_name} successfully."
    except Exception as e:
        logger.error(f"open_app failed for '{app_name}': {e}")
        return f"Failed to open {app_name}: {e}"


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
    # Try wmctrl on X11; on Wayland this usually fails
    if shutil.which("wmctrl") and SESSION_TYPE == "x11":
        try:
            out = subprocess.check_output(
                ["wmctrl", "-l"], stderr=subprocess.DEVNULL, timeout=3
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

    if SESSION_TYPE == "wayland":
        note = " (Wayland: window titles unavailable; showing process names)"
    else:
        note = ""
    return f"Running processes{note}: " + ", ".join(sorted(procs)[:20])
