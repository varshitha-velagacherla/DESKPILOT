"""
screen_tools.py — Linux port

Changes from Windows version:
  - Replaced hardcoded C:/Users/venkatesh buddhi/Pictures/Screenshots
    with platform-neutral Path.home() / "Pictures" / "Screenshots"
  - mkdir(parents=True, exist_ok=True) ensures the folder exists
"""

import tempfile
from pathlib import Path
from langchain_core.tools import tool
import datetime


@tool
def take_screenshot() -> str:
    """
    Take a screenshot of the current screen and save it to ~/Pictures/Screenshots/.
    """
    try:
        import mss
        from PIL import Image

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        save_dir  = Path.home() / "Pictures" / "Screenshots"
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = str(save_dir / f"Screenshot_{timestamp}.png")

        with mss.mss() as sct:
            monitor    = sct.monitors[1]   # primary monitor
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img.save(save_path)

        return f"Screenshot saved to {save_path}"
    except Exception as e:
        return f"Screenshot failed: {e}"