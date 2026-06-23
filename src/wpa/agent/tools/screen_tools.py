import os
import tempfile
from pathlib import Path
from langchain_core.tools import tool
import datetime


@tool
def take_screenshot() -> str:
    """
    Take a screenshot of the current screen and save it.
    Optionally provide a save_path; defaults to Desktop.
    """
    try:
        import mss
        from PIL import Image
        # Add data as filename suffix (for example)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M%S")
        save_path = str(Path("C:/Users/venkatesh buddhi/Pictures/Screenshots") / f"Screenshot {timestamp}.png")

        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img.save(save_path)
        
        return f"Screenshot saved to {save_path}"
    except Exception as e:
        return f"Screenshot failed: {e}"



# # Test
# print("\n🧪 Testing take_screenshot...")
# print(take_screenshot.invoke({}))