import psutil
import platform
import datetime
import pyperclip
from langchain_core.tools import tool
import pyautogui

@tool
def get_system_info() -> str:
    """
    Get current system status: CPU, RAM, battery, disk, and time.
    Use when user asks about system performance or specs.
    """
    cpu      = psutil.cpu_percent(interval=1)
    ram      = psutil.virtual_memory()
    disk     = psutil.disk_usage("/")
    battery  = psutil.sensors_battery()
    now      = datetime.datetime.now().strftime("%A %B %d, %I:%M %p")

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
    mins   = battery.secsleft // 60 if battery.secsleft > 0 else None
    time_left = f", about {mins} minutes remaining" if mins else ""
    return f"Battery is at {battery.percent:.0f}%, {status}{time_left}."


@tool
def set_volume(level: int) -> str:
    """
    Set Windows system volume using keyboard events.
    Volume level must be between 0 and 100.
    """

    if not 0 <= level <= 100:
        return "Volume must be between 0 and 100."

    try:
        # First mute volume completely
        for _ in range(50):
            pyautogui.press("volumedown")

        # Increase to desired level
        steps = int(level / 2)  # Approximation: 50 steps ≈ 100%

        for _ in range(steps):
            pyautogui.press("volumeup")

        return f"Volume set approximately to {level}%."

    except Exception as e:
        return f"Could not set volume: {e}"


@tool
def get_clipboard() -> str:
    """Read the current text content of the clipboard."""
    try:
        content = pyperclip.paste()
        if not content:
            return "Clipboard is empty."
        return f"Clipboard contains: {content[:500]}"  # limit to 500 chars
    except Exception as e:
        return f"Could not read clipboard: {e}"


@tool
def set_clipboard(text: str) -> str:
    """Copy text to the clipboard."""
    try:
        pyperclip.copy(text)
        return f"Copied to clipboard: {text[:100]}"
    except Exception as e:
        return f"Could not write to clipboard: {e}"


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    now = datetime.datetime.now()
    return now.strftime("It is %A, %B %d %Y, %I:%M %p")


# print("\n🧪 Testing get_system_info...")
# print(get_system_info.invoke({}))

# print("\n🧪 Testing get_battery_status...")
# print(get_battery_status.invoke({}))

# print("\n🧪 Testing get_current_time...")
# print(get_current_time.invoke({}))