"""
tool_executor.py — Linux port

Changes from Windows version:
  - Replaced entire Windows APP_MAP block (hardcoded C:\\ paths) with Linux
    shutil.which()-based resolution via platform_utils.resolve_app_command()
  - Removed time.sleep(2)/is_process_running hard verification (unreliable
    for Flatpak/snap apps on Linux) — replaced with a shorter 0.5s check
  - APP_MAP is now defined in src/deskpilot/system/platform_utils.py (LINUX_APP_MAP)
  - All other logic (COMMON_SITES, tool routing, etc.) is unchanged
"""

import logging
from typing import Tuple

from .tools import ALL_TOOLS
from src.deskpilot.agent.tools.app_tools import launch_app

logger = logging.getLogger("deskpilot.executor")

COMMON_SITES = {
    # Google ecosystem
    "google":       "https://www.google.com",
    "gmail":        "https://mail.google.com",
    "youtube":      "https://www.youtube.com",
    "drive":        "https://drive.google.com",
    "maps":         "https://maps.google.com",
    # Social media
    "linkedin":     "https://www.linkedin.com",
    "instagram":    "https://www.instagram.com",
    "facebook":     "https://www.facebook.com",
    "twitter":      "https://twitter.com",
    "x":            "https://twitter.com",
    "reddit":       "https://www.reddit.com",
    # Messaging
    "whatsapp":     "https://web.whatsapp.com",
    "telegram":     "https://web.telegram.org",
    "discord":      "https://discord.com/app",
    # Developer
    "github":       "https://github.com",
    "gitlab":       "https://gitlab.com",
    "stackoverflow": "https://stackoverflow.com",
    # AI
    "chatgpt":      "https://chat.openai.com",
    "claude":       "https://claude.ai",
    "gemini":       "https://gemini.google.com",
    # Entertainment
    "netflix":      "https://www.netflix.com",
    "spotify":      "https://open.spotify.com",
    "prime video":  "https://www.primevideo.com",
    # Productivity
    "notion":       "https://www.notion.so",
    "canva":        "https://www.canva.com",
    # Shopping
    "amazon":       "https://www.amazon.in",
    "flipkart":     "https://www.flipkart.com",
}

# Build lookup map once at import time
_tool_map = {}
for t in ALL_TOOLS:
    if hasattr(t, "name"):
        _tool_map[t.name] = t
    elif hasattr(t, "__name__"):
        _tool_map[t.__name__] = t


def is_process_running(name: str) -> bool:
    if not name:
        return False
    name = name.lower().split()[0]  # handle "libreoffice --writer" → "libreoffice"
    for proc in psutil.process_iter(["name"]):
        proc_name = (proc.info.get("name") or "").lower()
        if name in proc_name or proc_name in name:
            return True
    return False


def execute_tool(tool_name: str, tool_args: dict) -> Tuple[bool, str]:
    """
    Execute a tool by name with given args.
    Returns: (success: bool, result: str)
    Never raises — always returns a result string.
    """
    # ── URL normalisation ─────────────────────────────────────────────────────
    if tool_name == "open_url":
        url = tool_args.get("url", "").strip().lower()
        if url in COMMON_SITES:
            url = COMMON_SITES[url]
        elif not url.startswith(("http://", "https://")):
            url = "https://" + url
        tool_args["url"] = url

    if tool_name not in _tool_map:
        msg = f"Tool '{tool_name}' not found. Available: {list(_tool_map.keys())}"
        return False, msg

    # ── Verified Linux app launch ─────────────────────────────────────────────
    if tool_name == "open_app":
        app_name = tool_args.get("app_name", "").strip()
        try:
            return launch_app(app_name)
        except Exception as e:
            msg = f"I couldn't open {app_name or 'that application'}."
            logger.error(f"[executor] open_app failed for '{app_name}': {e}")
            return False, msg

    try:
        tool = _tool_map[tool_name]
        result = tool.invoke(tool_args)
        result_str = str(result).strip()
        return True, result_str

    except TypeError as e:
        msg = f"Wrong arguments for {tool_name}: {e}"
        logger.error(f"[executor] {msg}")
        return False, msg

    except Exception as e:
        msg = f"Tool {tool_name} failed: {e}"
        logger.error(f"[executor] {msg}")
        return False, msg


def get_available_tools() -> list:
    """Return list of all registered tool names."""
    return list(_tool_map.keys())
