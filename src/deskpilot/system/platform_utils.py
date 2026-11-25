"""
platform_utils.py — Linux Platform Abstraction Layer

Provides Linux replacements for all Windows-specific system calls:
  - Session type detection (X11 vs Wayland)
  - Volume control via wpctl (PipeWire), pactl, or amixer
  - Clipboard via xclip/xsel (X11) or wl-clipboard (Wayland)
  - File/folder opening via xdg-open
  - App launching with shutil.which priority lists
  - Log folder opening

All functions use shutil.which() before calling external tools and
log a clear warning instead of crashing if a tool is missing.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger("deskpilot.platform")

# ── Environment sanitization ──────────────────────────────────────────────────

_ENV_VARS_TO_REMOVE = {
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "PYTHONHOME",
    "PYTHONPATH",
}

_CONTAMINATED_PATH_TOKENS = ("conda", "miniconda", "anaconda", ".venv")

_REQUIRED_SYSTEM_PATHS = ("/usr/bin", "/bin", "/usr/local/bin", "/snap/bin")


def build_clean_env(
    base_env: Optional[Mapping[str, str]] = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """
    Build a clean environment for launching desktop applications.

    Preserves graphical session variables (DISPLAY, WAYLAND_DISPLAY, XAUTHORITY,
    XDG_RUNTIME_DIR, DBUS_SESSION_BUS_ADDRESS, HOME, XDG_*) while stripping
    Conda/venv/library overrides that break Snap and native GNOME apps.
    """
    source = dict(os.environ if base_env is None else base_env)
    clean_env: dict[str, str] = {}
    removed_vars: list[str] = []

    for key, value in source.items():
        if key in _ENV_VARS_TO_REMOVE or key.startswith("CONDA_"):
            removed_vars.append(key)
            continue
        clean_env[key] = value

    raw_path = source.get("PATH", "")
    kept_parts: list[str] = []
    removed_path_entries: list[str] = []

    for entry in raw_path.split(os.pathsep):
        if not entry:
            continue
        lower_entry = entry.lower()
        if any(tok in lower_entry for tok in _CONTAMINATED_PATH_TOKENS):
            removed_path_entries.append(entry)
            continue
        if entry not in kept_parts:
            kept_parts.append(entry)

    added_path_entries: list[str] = []
    for sys_dir in _REQUIRED_SYSTEM_PATHS:
        if sys_dir not in kept_parts:
            kept_parts.append(sys_dir)
            added_path_entries.append(sys_dir)

    clean_env["PATH"] = os.pathsep.join(kept_parts)

    env_diff = {
        "removed_vars": sorted(removed_vars),
        "removed_path_entries": removed_path_entries,
        "added_path_entries": added_path_entries,
    }
    return clean_env, env_diff


# ── Session type ──────────────────────────────────────────────────────────────

def detect_session_type(env: Optional[Mapping[str, str]] = None) -> str:
    """Return 'wayland', 'x11', or 'unknown'."""
    source = os.environ if env is None else env
    session = source.get("XDG_SESSION_TYPE", "").lower()
    if session in ("wayland", "x11"):
        return session
    # Fallback: check WAYLAND_DISPLAY
    if source.get("WAYLAND_DISPLAY"):
        return "wayland"
    if source.get("DISPLAY"):
        return "x11"
    return "unknown"


SESSION_TYPE = detect_session_type()


# ── Volume control ────────────────────────────────────────────────────────────

def set_volume_linux(level: int) -> str:
    """
    Set system volume (0–100) using wpctl, pactl, or amixer (in that order).
    wpctl is preferred because this machine uses PipeWire.
    """
    if not 0 <= level <= 100:
        return "Volume must be between 0 and 100."

    fraction = level / 100.0  # wpctl uses 0.0–1.0

    # 1. Try wpctl (PipeWire / WirePlumber)
    if shutil.which("wpctl"):
        try:
            subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{fraction:.2f}"],
                check=True, capture_output=True
            )
            return f"Volume set to {level}%."
        except subprocess.CalledProcessError as e:
            logger.warning(f"wpctl failed: {e}")

    # 2. Try pactl (PulseAudio / PipeWire-pulse)
    if shutil.which("pactl"):
        try:
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                check=True, capture_output=True
            )
            return f"Volume set to {level}%."
        except subprocess.CalledProcessError as e:
            logger.warning(f"pactl failed: {e}")

    # 3. Fallback: amixer
    if shutil.which("amixer"):
        try:
            subprocess.run(
                ["amixer", "-q", "set", "Master", f"{level}%"],
                check=True, capture_output=True
            )
            return f"Volume set to {level}% (via amixer)."
        except subprocess.CalledProcessError as e:
            logger.warning(f"amixer failed: {e}")

    return "Could not set volume: no audio control tool found (wpctl/pactl/amixer)."


def get_volume_linux() -> str:
    """Get current system volume percentage."""
    if shutil.which("wpctl"):
        try:
            out = subprocess.check_output(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                stderr=subprocess.DEVNULL
            ).decode()
            # output: "Volume: 0.50\n" or "Volume: 0.50 [MUTED]\n"
            parts = out.split()
            if len(parts) >= 2:
                vol = int(float(parts[1]) * 100)
                muted = "[MUTED]" in out
                return f"{vol}%{' (muted)' if muted else ''}"
        except Exception as e:
            logger.warning(f"wpctl get-volume failed: {e}")
    return "unknown"


# ── Clipboard ─────────────────────────────────────────────────────────────────

def get_clipboard_linux() -> str:
    """Read clipboard contents, preferring xclip/xsel on X11, wl-paste on Wayland."""
    # Wayland first
    if SESSION_TYPE == "wayland" and shutil.which("wl-paste"):
        try:
            out = subprocess.check_output(
                ["wl-paste", "--no-newline"], stderr=subprocess.DEVNULL
            ).decode(errors="replace")
            return out
        except subprocess.CalledProcessError:
            return ""

    # X11 / fallback
    if shutil.which("xclip"):
        try:
            out = subprocess.check_output(
                ["xclip", "-selection", "clipboard", "-o"],
                stderr=subprocess.DEVNULL
            ).decode(errors="replace")
            return out
        except subprocess.CalledProcessError:
            return ""

    if shutil.which("xsel"):
        try:
            out = subprocess.check_output(
                ["xsel", "--clipboard", "--output"],
                stderr=subprocess.DEVNULL
            ).decode(errors="replace")
            return out
        except subprocess.CalledProcessError:
            return ""

    logger.warning("get_clipboard: no clipboard tool found (xclip/xsel/wl-paste)")
    return ""


def set_clipboard_linux(text: str) -> str:
    """Write text to clipboard, preferring wl-copy on Wayland, xclip/xsel on X11."""
    encoded = text.encode()

    if SESSION_TYPE == "wayland" and shutil.which("wl-copy"):
        try:
            proc = subprocess.run(["wl-copy"], input=encoded, check=True, capture_output=True)
            return f"Copied to clipboard: {text[:100]}"
        except subprocess.CalledProcessError as e:
            logger.warning(f"wl-copy failed: {e}")

    if shutil.which("xclip"):
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=encoded, check=True, capture_output=True
            )
            return f"Copied to clipboard: {text[:100]}"
        except subprocess.CalledProcessError as e:
            logger.warning(f"xclip failed: {e}")

    if shutil.which("xsel"):
        try:
            subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=encoded, check=True, capture_output=True
            )
            return f"Copied to clipboard: {text[:100]}"
        except subprocess.CalledProcessError as e:
            logger.warning(f"xsel failed: {e}")

    return "Could not write to clipboard: no clipboard tool found (xclip/xsel/wl-copy)."


# ── File / folder opening ─────────────────────────────────────────────────────

def open_path(path: str) -> bool:
    """Open a file or folder with the default application (xdg-open)."""
    if not shutil.which("xdg-open"):
        logger.warning("open_path: xdg-open not found")
        return False
    try:
        subprocess.Popen(["xdg-open", str(path)], start_new_session=True)
        return True
    except Exception as e:
        logger.warning(f"xdg-open failed: {e}")
        return False


def open_logs_folder(logs_path: str = "logs") -> bool:
    """Open the logs folder in the default file manager."""
    p = Path(logs_path).resolve()
    p.mkdir(exist_ok=True)
    return open_path(str(p))


# ── App launching ─────────────────────────────────────────────────────────────

# Config-driven Linux app map.
# Each entry is a list of candidates tried in order via shutil.which().
# The first one found on the system is used.
# Use tuples: (display_name, [candidate_executables])
LINUX_APP_MAP: dict[str, list[str]] = {
    # Browsers
    "chrome":           ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    "google chrome":    ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    "chromium":         ["chromium", "chromium-browser", "google-chrome-stable"],
    "firefox":          ["/snap/bin/firefox", "snap run firefox", "firefox", "firefox-esr"],
    "edge":             ["microsoft-edge", "microsoft-edge-stable"],
    # Editors
    "vscode":           ["code", "code-oss", "codium"],
    "vs code":          ["code", "code-oss", "codium"],
    "visual studio code": ["code", "code-oss", "codium"],
    "gedit":            ["gedit", "gnome-text-editor"],
    "notepad":          ["gedit", "gnome-text-editor", "kate", "mousepad"],
    "wordpad":          ["libreoffice", "abiword"],
    "kate":             ["kate"],
    # Terminals
    "terminal":         ["gnome-terminal", "konsole", "xterm", "tilix", "alacritty"],
    "cmd":              ["gnome-terminal", "konsole", "xterm"],
    "powershell":       ["pwsh", "gnome-terminal", "konsole", "xterm"],
    # File managers
    "file explorer":    ["nautilus", "nemo", "thunar", "dolphin"],
    "fileexplorer":     ["nautilus", "nemo", "thunar", "dolphin"],
    "files":            ["nautilus", "nemo", "thunar"],
    "nautilus":         ["nautilus"],
    # System tools
    "calculator":       ["gnome-calculator", "kcalc", "qalculate-gtk"],
    "task manager":     ["gnome-system-monitor", "htop", "btop"],
    "taskmanager":      ["gnome-system-monitor", "htop"],
    "system monitor":   ["gnome-system-monitor"],
    "settings":         ["gnome-control-center", "systemsettings5"],
    "paint":            ["gimp", "pinta", "kolourpaint"],
    "snipping tool":    ["gnome-screenshot", "scrot", "flameshot"],
    # Media
    "vlc":              ["vlc"],
    "spotify":          ["spotify", "flatpak run com.spotify.Client"],
    "rhythmbox":        ["rhythmbox"],
    "totem":            ["totem"],
    # Office
    "word":             ["libreoffice --writer"],
    "excel":            ["libreoffice --calc"],
    "powerpoint":       ["libreoffice --impress"],
    "libreoffice":      ["libreoffice"],
    # PDF
    "evince":           ["evince"],
}


APP_DESKTOP_IDS: dict[str, list[str]] = {
    "firefox":            ["firefox_firefox.desktop", "firefox.desktop"],
    "chrome":             ["google-chrome.desktop", "chromium_chromium.desktop", "chromium.desktop"],
    "google chrome":      ["google-chrome.desktop", "chromium_chromium.desktop"],
    "chromium":           ["chromium_chromium.desktop", "chromium.desktop"],
    "calculator":         ["org.gnome.Calculator.desktop", "gnome-calculator.desktop"],
    "gnome-calculator":   ["org.gnome.Calculator.desktop", "gnome-calculator.desktop"],
    "terminal":           ["org.gnome.Terminal.desktop", "gnome-terminal.desktop"],
    "gnome-terminal":     ["org.gnome.Terminal.desktop", "gnome-terminal.desktop"],
    "file explorer":      ["org.gnome.Nautilus.desktop", "nautilus.desktop"],
    "fileexplorer":       ["org.gnome.Nautilus.desktop", "nautilus.desktop"],
    "files":              ["org.gnome.Nautilus.desktop", "nautilus.desktop"],
    "nautilus":           ["org.gnome.Nautilus.desktop", "nautilus.desktop"],
    "vscode":             ["code_code.desktop", "code.desktop"],
    "vs code":            ["code_code.desktop", "code.desktop"],
    "visual studio code": ["code_code.desktop", "code.desktop"],
    "code":               ["code_code.desktop", "code.desktop"],
    "gedit":              ["org.gnome.gedit.desktop", "org.gnome.TextEditor.desktop", "gedit.desktop"],
    "notepad":            ["org.gnome.TextEditor.desktop", "org.gnome.gedit.desktop", "gedit.desktop"],
    "settings":           ["gnome-control-center.desktop", "org.gnome.Settings.desktop"],
    "system monitor":     ["gnome-system-monitor.desktop", "org.gnome.SystemMonitor.desktop"],
    "task manager":       ["gnome-system-monitor.desktop", "org.gnome.SystemMonitor.desktop"],
    "spotify":            ["spotify_spotify.desktop", "com.spotify.Client.desktop", "spotify.desktop"],
    "vlc":                ["vlc.desktop"],
    "evince":             ["org.gnome.Evince.desktop", "evince.desktop"],
    "libreoffice":        ["libreoffice-startcenter.desktop"],
}


def _desktop_search_dirs(env: Optional[Mapping[str, str]] = None) -> list[Path]:
    """Return directories containing .desktop entries in priority order."""
    source = os.environ if env is None else env
    dirs: list[Path] = [
        Path.home() / ".local/share/applications",
        Path("/var/lib/snapd/desktop/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        Path.home() / ".local/share/flatpak/exports/share/applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
    ]
    xdg_data_dirs = source.get("XDG_DATA_DIRS", "")
    for base in xdg_data_dirs.split(os.pathsep):
        if base:
            p = Path(base) / "applications"
            if p not in dirs:
                dirs.append(p)
    return dirs


def find_desktop_file(
    desktop_id: str,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """Find a .desktop file on disk for the given desktop ID."""
    for d in _desktop_search_dirs(env):
        candidate = d / desktop_id
        if candidate.is_file():
            return candidate
    return None


def resolve_executable(
    exe: str,
    clean_env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Resolve an executable using clean_env PATH or absolute path."""
    if os.path.isabs(exe):
        if os.path.isfile(exe) and os.access(exe, os.X_OK):
            return exe
        return None
    path_str = (clean_env or {}).get("PATH") if clean_env is not None else build_clean_env()[0].get("PATH")
    return shutil.which(exe, path=path_str)


def detect_install_type(
    cmd_parts: list[str],
    resolved_path: Optional[str] = None,
    desktop_file: Optional[Path] = None,
) -> str:
    """Classify installation type as 'snap', 'flatpak', or 'apt'."""
    cmd_str = " ".join(cmd_parts)
    exe_base = os.path.basename(cmd_parts[0]) if cmd_parts else ""
    if (
        (resolved_path and "/snap/" in resolved_path)
        or (cmd_parts and cmd_parts[0].startswith("/snap/"))
        or (exe_base == "snap" and len(cmd_parts) > 1 and cmd_parts[1] == "run")
        or cmd_str.startswith("snap run ")
        or (desktop_file and "/snapd/" in str(desktop_file))
    ):
        return "snap"
    if (
        (exe_base == "flatpak" and len(cmd_parts) > 1 and cmd_parts[1] == "run")
        or cmd_str.startswith("flatpak run ")
        or (desktop_file and "flatpak" in str(desktop_file))
    ):
        return "flatpak"
    return "apt"


def resolve_app_command(
    app_name: str,
    clean_env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """
    Find the first available executable for a given app name.
    Returns the command string, or None if nothing found.
    Checks explicit paths and shutil.which() with a clean PATH.
    """
    if clean_env is None:
        clean_env, _ = build_clean_env()

    key = app_name.lower().strip()
    candidates = LINUX_APP_MAP.get(key, [key])

    for candidate in candidates:
        parts = candidate.split()
        exe = parts[0]
        if resolve_executable(exe, clean_env):
            return candidate

    # Not found in map — try the raw name
    if resolve_executable(key, clean_env):
        return key

    logger.warning(f"resolve_app_command: no executable found for '{app_name}'")
    return None


def _is_url_or_path(target: str) -> bool:
    """Return True if target looks like a URL or existing local file/directory."""
    lower = target.lower().strip()
    if lower.startswith(("http://", "https://", "file://", "mailto:")):
        return True
    expanded = os.path.expanduser(target.strip())
    return os.path.exists(expanded)


def build_launch_plan(
    app_name: str,
    clean_env: Mapping[str, str],
) -> list[dict[str, Any]]:
    """
    Build ordered launch candidates for an app:
      1) App map command(s) (with /snap/bin/firefox and snap run firefox for Firefox)
      2) gtk-launch with matching .desktop ID
      3) xdg-open for URLs and local files
    """
    raw = app_name.strip()
    key = raw.lower()
    plan: list[dict[str, Any]] = []
    seen_cmds: set[tuple[str, ...]] = set()

    # 1) App map commands (or raw executable name)
    candidates = list(LINUX_APP_MAP.get(key, []))
    if key and key not in candidates:
        candidates.append(key)

    for candidate in candidates:
        parts = candidate.split()
        if not parts:
            continue
        resolved = resolve_executable(parts[0], clean_env)
        if not resolved:
            continue
        exec_parts = [parts[0] if os.path.isabs(parts[0]) else resolved] + parts[1:]
        cmd_key = tuple(exec_parts)
        if cmd_key in seen_cmds:
            continue
        seen_cmds.add(cmd_key)
        plan.append({
            "strategy": "app_map",
            "cmd_parts": exec_parts,
            "resolved_path": resolved,
            "install_type": detect_install_type(exec_parts, resolved_path=resolved),
            "desktop_id": None,
        })

    # 2) gtk-launch with matching .desktop ID
    gtk_launch_path = resolve_executable("gtk-launch", clean_env)
    if gtk_launch_path:
        desktop_ids = list(APP_DESKTOP_IDS.get(key, []))
        for fallback_id in (f"{key}.desktop", f"{key}_{key}.desktop"):
            if key and fallback_id not in desktop_ids:
                desktop_ids.append(fallback_id)
        for desktop_id in desktop_ids:
            desktop_file = find_desktop_file(desktop_id, clean_env)
            if desktop_file is not None:
                exec_parts = [gtk_launch_path, desktop_id]
                cmd_key = tuple(exec_parts)
                if cmd_key not in seen_cmds:
                    seen_cmds.add(cmd_key)
                    plan.append({
                        "strategy": "gtk-launch",
                        "cmd_parts": exec_parts,
                        "resolved_path": gtk_launch_path,
                        "install_type": detect_install_type(exec_parts, desktop_file=desktop_file),
                        "desktop_id": desktop_id,
                    })

    # 3) xdg-open for URLs and files
    if _is_url_or_path(raw):
        xdg_open_path = resolve_executable("xdg-open", clean_env)
        if xdg_open_path:
            target = os.path.expanduser(raw) if not raw.lower().startswith(("http://", "https://", "file://", "mailto:")) else raw
            exec_parts = [xdg_open_path, target]
            cmd_key = tuple(exec_parts)
            if cmd_key not in seen_cmds:
                seen_cmds.add(cmd_key)
                plan.append({
                    "strategy": "xdg-open",
                    "cmd_parts": exec_parts,
                    "resolved_path": xdg_open_path,
                    "install_type": "apt",
                    "desktop_id": None,
                })

    return plan
