from .app_tools    import open_app, close_app, list_running_apps
from .file_tools   import search_files, read_file, write_file, delete_file, list_directory
from .system_tools import get_system_info, get_battery_status, set_volume, get_clipboard, set_clipboard, get_current_time
from .web_tools    import open_url, web_search, search_and_open
from .screen_tools import take_screenshot

# ── This is the ONLY list you pass to the LLM ────────────────────────────────
ALL_TOOLS = [
    # App control
    open_app,
    close_app,
    list_running_apps,
    # File operations
    search_files,
    read_file,
    write_file,
    delete_file,
    list_directory,
    # System
    get_system_info,
    get_battery_status,
    set_volume,
    get_clipboard,
    set_clipboard,
    get_current_time,
    # Web
    open_url,
    web_search,
    search_and_open,
    # Screen
    take_screenshot,
]
