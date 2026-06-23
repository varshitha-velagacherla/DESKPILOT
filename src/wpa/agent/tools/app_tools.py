
import subprocess
import psutil
import os
from langchain_core.tools import tool

# Common app name → executable mapping
APP_MAP = {
    "notepad":       "notepad.exe",
    "calculator":    "calc.exe",
    "explorer":      "explorer.exe",
    "chrome":        "chrome.exe",
    "vscode":        "code",
    "vs code":       "code",
    "terminal":      "wt.exe",
    "cmd":           "cmd.exe",
    "task manager":  "taskmgr.exe",
    "paint":         "mspaint.exe",
    "word":          "winword.exe",
    "excel":         "excel.exe",
    "powerpoint":    "powerpnt.exe",
    "spotify":       "spotify.exe",
    "firefox":       "firefox.exe",
    "edge":          "msedge.exe",
    "vlc":           "vlc.exe",
}


@tool
def open_app(app_name: str) -> str:
    """Open an application by name. Examples: notepad, chrome, vscode, calculator."""
    key = app_name.lower().strip()
    executable = APP_MAP.get(key, key)  # fallback: use name as-is
    
    try:
        subprocess.Popen(
            executable,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return f"Opened {app_name} successfully."
    except Exception as e:
        return f"Failed to open {app_name}: {e}"


@tool
def close_app(app_name: str) -> str:
    """Close a running application by name. Example: close notepad, close chrome."""
    key = app_name.lower().strip()
    executable = APP_MAP.get(key, key)
    
    # Strip .exe if present for psutil matching
    proc_name = executable.replace(".exe", "").lower()
    
    killed = []
    for proc in psutil.process_iter(["name", "pid"]):
        if proc_name in proc.info["name"].lower():
            proc.terminate()
            killed.append(proc.info["name"])
    
    if killed:
        return f"Closed: {', '.join(set(killed))}"
    return f"No running process found for \'{app_name}\'"


@tool
def list_running_apps() -> str:
    """List all currently running applications (visible windows only)."""
    try:
        import pygetwindow as gw
        windows = gw.getAllTitles()
        visible = [w for w in windows if w.strip()]
        if not visible:
            return "No visible windows found."
        return "Running apps: " + ", ".join(visible[:15])  # limit to 15
    except Exception:
        # Fallback: use psutil
        procs = set()
        for p in psutil.process_iter(["name"]):
            try:
                procs.add(p.info["name"])
            except Exception:
                pass
        return "Running processes: " + ", ".join(sorted(procs)[:20])
