
"""
tool_executor.py

Pure Python tool execution. No LLM involved.
Receives tool_name + tool_args, runs the tool, returns result.

"""

import logging
from typing import Tuple
import time
import psutil

from .tools import ALL_TOOLS

logger = logging.getLogger("wpa.executor")

COMMON_SITES = {

        # Google ecosystem
        "google":      "https://www.google.com",
        "gmail":       "https://mail.google.com",
        "youtube":     "https://www.youtube.com",
        "drive":       "https://drive.google.com",
        "maps":        "https://maps.google.com",

        # Social media
        "linkedin":    "https://www.linkedin.com",
        "instagram":   "https://www.instagram.com",
        "facebook":    "https://www.facebook.com",
        "twitter":     "https://twitter.com",
        "x":           "https://twitter.com",
        "reddit":      "https://www.reddit.com",

        # Messaging
        "whatsapp":    "https://web.whatsapp.com",
        "telegram":    "https://web.telegram.org",
        "discord":     "https://discord.com/app",

        # Developer
        "github":      "https://github.com",
        "gitlab":      "https://gitlab.com",
        "stackoverflow":"https://stackoverflow.com",

        # AI
        "chatgpt":     "https://chat.openai.com",
        "claude":      "https://claude.ai",
        "gemini":      "https://gemini.google.com",

        # Entertainment
        "netflix":     "https://www.netflix.com",
        "spotify":     "https://open.spotify.com",
        "prime video": "https://www.primevideo.com",

        # Productivity
        "notion":      "https://www.notion.so",
        "canva":       "https://www.canva.com",

        # Shopping
        "amazon":      "https://www.amazon.in",
        "flipkart":    "https://www.flipkart.com",

    }

# Build lookup map once at import time
_tool_map = {}

for t in ALL_TOOLS:

    if hasattr(t, "name"):
        _tool_map[t.name] = t

    elif hasattr(t, "__name__"):
        _tool_map[t.__name__] = t

    else:
        # logger.warning(
        #     f"[executor] could not register tool: {repr(t)[:60]}"
        # )

        pass

# logger.info(
#     f"[executor] registered {len(_tool_map)} tools: "
#     f"{list(_tool_map.keys())}"
# )

def is_process_running(name: str) -> bool:

    if not name:
        return False

    name = name.lower()

    for proc in psutil.process_iter(["name"]):

        proc_name = proc.info.get("name")

        if not proc_name:
            continue

        proc_name = proc_name.lower()

        if (
            name in proc_name or
            proc_name in name
        ):
            return True

    return False

def execute_tool(tool_name: str, tool_args: dict) -> Tuple[bool, str]:
    """
    Execute a tool by name with given args.

    Returns:
        (success: bool, result: str)

    Never raises — always returns a result string.
    """

    # logger.info(
    #     f"[executor] running {tool_name}({tool_args})"
    # )

    if tool_name == "open_url":

        url = tool_args.get("url", "")
        url = url.strip().lower()
        if url in COMMON_SITES:
            url = COMMON_SITES[url]
        elif not url.startswith(("http://", "https://")):
            url = "https://" + url
        tool_args["url"] = url

    if tool_name not in _tool_map:

        msg = (
            f"Tool '{tool_name}' not found. "
            f"Available: {list(_tool_map.keys())}"
        )

        # logger.error(f"[executor] {msg}")

        return False, msg
    
    # ── Deterministic app resolution ─────────────────────────────────────────────

    if tool_name == "open_app":

        app_name = (
            tool_args.get("app_name", "")
            .lower()
            .strip()
        )

        APP_MAP = {

            # ── Browsers ─────────────────────────────────────────────────────────────

            "chrome":
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",

            "google chrome":
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",

            "edge":
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",

            "microsoft edge":
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",

            "firefox":
                r"C:\Program Files\Mozilla Firefox\firefox.exe",

            # ── Editors / IDEs ───────────────────────────────────────────────────────

            "notepad":
                r"C:\Windows\System32\notepad.exe",

            "wordpad":
                r"C:\Program Files\Windows NT\Accessories\wordpad.exe",

            "vscode":
                r"C:\Users\venkatesh buddhi\AppData\Local\Programs\Microsoft VS Code\Code.exe",

            "vs code":
                r"C:\Users\venkatesh buddhi\AppData\Local\Programs\Microsoft VS Code\Code.exe",

            "visual studio code":
                r"C:\Users\venkatesh buddhi\AppData\Local\Programs\Microsoft VS Code\Code.exe",

            # ── Media ────────────────────────────────────────────────────────────────

            "vlc":
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",

            "spotify":
                "start spotify:",

            # ── Windows Apps ─────────────────────────────────────────────────────────

            "calculator":
                r"C:\Windows\System32\calc.exe",

            "paint":
                r"C:\Windows\System32\mspaint.exe",

            "task manager":
                r"C:\Windows\System32\Taskmgr.exe",
            "taskmanager":
                r"C:\Windows\System32\Taskmgr.exe",

            "snipping tool":
                r"C:\Windows\System32\SnippingTool.exe",

            "file explorer":
                r"C:\Windows\explorer.exe",
            "fileexplorer":
                r"C:\Windows\explorer.exe",

            # ── Special Windows URI Apps ────────────────────────────────────────────

            "control panel":
                r"C:\Windows\System32\control.exe",

            # ── Utilities ────────────────────────────────────────────────────────────

            "cmd":
                "cmd.exe",

            "powershell":
                r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",

            "terminal":
                r"C:\Program Files\WindowsApps\Microsoft.WindowsTerminal_8wekyb3d8bbwe\wt.exe",


            # ── Office ───────────────────────────────────────────────────────────────

            "word":
                r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",

            "excel":
                r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",

            "powerpoint":
                r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",

            "outlook":
                r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
        }

        if app_name in APP_MAP:

            tool_args["app_name"] = APP_MAP[app_name]

            # logger.info(
            #     f"[executor] resolved app "
            #     f"'{app_name}' -> '{APP_MAP[app_name]}'"
            # )

        else:

            logger.warning(
                f"[executor] unknown app: {app_name}"
            )

    try:
        tool = _tool_map[tool_name]

        result = tool.invoke(tool_args)

        result_str = str(result).strip()

        if tool_name == "open_app":

            app_name = tool_args.get("app_name", "")

            # Give app time to launch
            time.sleep(2)

            if not is_process_running(app_name):

                result_str = (
                    "Tool executed but app did not open. "
                    "Check app name or installation."
                )

                logger.warning(
                    f"[executor] app verification failed: "
                    f"{app_name}"
                )

                return False, result_str

        # logger.info(
        #     f"[executor] {tool_name} succeeded: "
        #     f"{result_str[:100]}"
        # )

        return True, result_str

    except TypeError as e:

        # Wrong args passed — arg name mismatch
        msg = f"Wrong arguments for {tool_name}: {e}"

        logger.error(f"[executor] {msg}")

        return False, msg

    except Exception as e:

        msg = f"Tool {tool_name} failed: {e}"

        logger.error(f"[executor] {msg}")

        return False, msg


def get_available_tools() -> list:
    """
    Return list of all registered tool names.
    """

    return list(_tool_map.keys())
