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
from typing import Optional

logger = logging.getLogger("wpa.platform")

# ── Session type ──────────────────────────────────────────────────────────────

def detect_session_type() -> str:
    """Return 'wayland', 'x11', or 'unknown'."""
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session in ("wayland", "x11"):
        return session
    # Fallback: check WAYLAND_DISPLAY
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
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
    "firefox":          ["firefox", "firefox-esr"],
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


def resolve_app_command(app_name: str) -> Optional[str]:
    """
    Find the first available executable for a given app name.
    Returns the command string, or None if nothing found.
    Checks shutil.which() for each candidate.
    """
    key = app_name.lower().strip()
    candidates = LINUX_APP_MAP.get(key, [key])

    for candidate in candidates:
        # Handle multi-word commands like "libreoffice --writer"
        exe = candidate.split()[0]
        if shutil.which(exe):
            return candidate  # return full command including args

    # Not found in map — try the raw name
    if shutil.which(key):
        return key

    logger.warning(f"resolve_app_command: no executable found for '{app_name}'")
    return None
