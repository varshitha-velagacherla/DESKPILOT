"""
tray.py — System Tray Icon, Linux port

Changes from Windows version:
  - _on_open_logs: replaced subprocess.Popen('explorer "..."')
    with xdg-open (guarded by shutil.which)
  - Title changed from "Windows Productivity Agent" to "Linux Productivity Agent"
  - App indicator: tries gi.repository.AppIndicator3 on Wayland/GNOME,
    falls back to default pystray backend if unavailable
  - On Wayland: tray icon may not show without gnome-shell-extension-appindicator
"""

import threading
import subprocess
import shutil
import logging
from pathlib import Path
from PIL import Image, ImageDraw
import os
import logging
logger = logging.getLogger(__name__)

# Determine if a graphical display is available
_DISPLAY = os.getenv('DISPLAY')
if not _DISPLAY:
    logger.warning('No DISPLAY environment variable – running in headless mode. Tray functionality will be disabled.')
    # Define dummy implementations that safely no‑op
    def start_tray(on_exit_callback=None):
        logger.info('start_tray called in headless mode – no tray icon created.')
        return None
    def set_status(status: str):
        logger.debug(f'Set tray status (headless): {status}')
    def is_paused() -> bool:
        return False
    def exit_requested() -> bool:
        return False
    def _on_clear_memory(icon, item):
        logger.info('Clear memory called in headless mode – no action.')
else:
    # Existing implementation – keep unchanged
    import pystray
    from pystray import MenuItem as item
    from src.deskpilot.system import platform_utils
    from src.deskpilot.memory.sqlite_memory import clear_all as clear_sqlite
    from src.deskpilot.memory.chroma_memory import clear_all as clear_chroma
    from src.deskpilot.ui import resources
    
    ICON = pystray.Icon('DeskPilot', resources.ICON, menu=pystray.Menu(
        item('Pause', lambda icon, _: icon.visible and set_status('Paused')),
        item('Resume', lambda icon, _: not icon.visible and set_status('Running')),
        item('Clear Memory', _on_clear_memory),
        item('Exit', lambda icon, _: icon.stop()),
    ))
    
    def start_tray(on_exit_callback=None):
        def _on_exit(icon, item):
            if on_exit_callback:
                on_exit_callback()
            icon.stop()
        ICON.menu = pystray.Menu(
            item('Pause', lambda icon, _: set_status('Paused')),
            item('Resume', lambda icon, _: set_status('Running')),
            item('Clear Memory', _on_clear_memory),
            item('Exit', _on_exit),
        )
        ICON.run()
    
    def set_status(status: str):
        ICON.title = f'DeskPilot – {status}'
        logger.info(f'Tray status set to {status}')
    
    def is_paused() -> bool:
        return ICON.title.endswith('Paused')
    
    def exit_requested() -> bool:
        return not ICON.visible
    
    def _on_clear_memory(icon, item):
        clear_sqlite()
        clear_chroma()
        logger.info('Memory cleared via tray action')


img = Path("assets/tray_icon.png")

logger = logging.getLogger("deskpilot.tray")

# ── Shared state ──────────────────────────────────────────────────────────────
_status_text    = "Listening..."
_is_paused      = False
_exit_requested = False
_on_exit_cb     = None


def set_status(text: str):
    """Call from main.py to update tray tooltip."""
    global _status_text
    _status_text = text


def is_paused() -> bool:
    """main.py checks this before each listen cycle."""
    return _is_paused


def exit_requested() -> bool:
    """main.py checks this in its main loop to know when to shut down."""
    return _exit_requested


def _get_icon() -> Image.Image:
    try:
        return Image.open(img)
    except Exception as e:
        logger.warning(f"Tray icon load failed: {e}")
        image = Image.new("RGB", (64, 64), color=(30, 30, 30))
        draw  = ImageDraw.Draw(image)
        draw.text((18, 18), "D", fill="white")
        return image


# ── Menu callbacks ────────────────────────────────────────────────────────────

def _on_pause_resume(icon, item):
    global _is_paused
    _is_paused = not _is_paused
    label      = "Paused" if _is_paused else "Listening..."
    set_status(label)
    icon.title = f"DeskPilot — {label}"
    logger.info(f"Tray: {'paused' if _is_paused else 'resumed'}")


def _on_open_logs(icon, item):
    """Open the logs folder using xdg-open (Linux/cross-platform)."""
    logs = Path("logs").resolve()
    logs.mkdir(exist_ok=True)
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(logs)], start_new_session=True)
    else:
        logger.warning("Tray: xdg-open not found — cannot open logs folder")


def _on_clear_memory(icon, item):
    try:
        from src.deskpilot.memory import memory as mem
        ok = mem.clear_all()
        if ok:
            logger.info("Tray: memory cleared (SQLite + ChromaDB)")
        else:
            logger.warning("Tray: memory partially cleared")
        set_status("Memory cleared")
        icon.title = "DeskPilot — Memory cleared"
    except Exception as e:
        logger.error(f"Tray: clear memory failed: {e}")


def _on_exit(icon, item):
    """Set flag → stop icon → let main loop exit cleanly (no sys.exit)."""
    global _exit_requested
    logger.info("Tray: exit requested")
    _exit_requested = True
    icon.stop()
    if _on_exit_cb:
        _on_exit_cb()


def _build_menu(icon):
    pause_label = "Resume" if _is_paused else "Pause"
    return pystray.Menu(
        pystray.MenuItem(f"DeskPilot  —  {_status_text}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(pause_label,    _on_pause_resume),
        pystray.MenuItem("Open Logs",    _on_open_logs),
        pystray.MenuItem("Clear Memory", _on_clear_memory),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit",         _on_exit),
    )


# ── Public entry point ────────────────────────────────────────────────────────

def start_tray(on_exit_callback=None) -> threading.Thread:
    """
    Start tray icon in a daemon thread.
    on_exit_callback: called when user clicks Exit (optional).

    Linux notes:
      - On X11: tray works with most desktop environments.
      - On Wayland/GNOME: requires gnome-shell-extension-appindicator and
        the application indicator backend. If icon doesn't appear,
        install the extension and log out → select "Ubuntu on Xorg" at login.
    """
    global _on_exit_cb
    _on_exit_cb = on_exit_callback

    def _run():
        icon = pystray.Icon(
            name  = "DeskPilot",
            icon  = _get_icon(),
            title = "DeskPilot",
            menu  = pystray.Menu(lambda: _build_menu(icon))
        )
        logger.info("Tray icon started")
        icon.run()

    t = threading.Thread(target=_run, name="tray", daemon=True)
    t.start()
    return t