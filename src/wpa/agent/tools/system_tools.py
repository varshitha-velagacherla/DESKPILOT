"""
system_tools.py — Linux port

Changes from Windows version:
  - Removed: import pyautogui (Windows keyboard volume simulation)
  - set_volume: now uses platform_utils.set_volume_linux() → wpctl/pactl/amixer
  - get_clipboard: now uses platform_utils.get_clipboard_linux() → xclip/xsel/wl-paste
  - set_clipboard: now uses platform_utils.set_clipboard_linux() → xclip/xsel/wl-copy
  - All other functions (get_system_info, get_battery_status, get_current_time)
    are already cross-platform via psutil/datetime — unchanged.
"""

import psutil
import platform
import datetime
import logging
from langchain_core.tools import tool

from src.wpa.system.platform_utils import (
    set_volume_linux,
    get_clipboard_linux,
    set_clipboard_linux,
)

logger = logging.getLogger("wpa.tools.system")


@tool
def get_system_info() -> str:
    """
    Get current system status: CPU, RAM, battery, disk, and time.
    Use when user asks about system performance or specs.
    """
    cpu     = psutil.cpu_percent(interval=1)
    ram     = psutil.virtual_memory()
    disk    = psutil.disk_usage("/")
    battery = psutil.sensors_battery()
    now     = datetime.datetime.now().strftime("%A %B %d, %I:%M %p")

    bat_str = (
        f"{battery.percent:.0f}% ({'charging' if battery.power_plugged else 'on battery'})"
        if battery else "N/A"
    )

    return (
        f"Time: {now} | "
        f"CPU: {cpu}% | "
        f"RAM: {ram.percent}% used ({ram.used // 1024**3}GB / {ram.total // 1024**3}GB) | "
        f"Disk: {disk.percent}% used | "
        f"Battery: {bat_str}"
    )


@tool
def get_battery_status() -> str:
    """Get the current battery percentage and charging status."""
    battery = psutil.sensors_battery()
    if not battery:
        return "No battery detected (desktop PC or sensor unavailable)."
    status = "charging" if battery.power_plugged else "discharging"
    mins   = battery.secsleft // 60 if battery.secsleft and battery.secsleft > 0 else None
    time_left = f", about {mins} minutes remaining" if mins else ""
    return f"Battery is at {battery.percent:.0f}%, {status}{time_left}."


@tool
def set_volume(level: int) -> str:
    """
    Set system volume using wpctl (PipeWire), pactl, or amixer.
    Volume level must be between 0 and 100.
    """
    return set_volume_linux(level)


@tool
def get_clipboard() -> str:
    """Read the current text content of the clipboard."""
    try:
        content = get_clipboard_linux()
        if not content:
            return "Clipboard is empty."
        return f"Clipboard contains: {content[:500]}"
    except Exception as e:
        return f"Could not read clipboard: {e}"


@tool
def set_clipboard(text: str) -> str:
    """Copy text to the clipboard."""
    try:
        return set_clipboard_linux(text)
    except Exception as e:
        return f"Could not write to clipboard: {e}"


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    now = datetime.datetime.now()
    return now.strftime("It is %A, %B %d %Y, %I:%M %p")