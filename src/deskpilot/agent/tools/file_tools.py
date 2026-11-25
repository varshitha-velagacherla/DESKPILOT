import os
from pathlib import Path
from langchain_core.tools import tool

# Default search roots — add more as needed
SEARCH_ROOTS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home(),
]


@tool
def search_files(filename: str, extension: str = "") -> str:
    """
    Search for files by name or extension on the PC.
    Examples: search_files(\'report\'), search_files(\'\', \'.pdf\')
    """
    matches = []
    pattern = f"*{filename}*" if filename else f"*{extension}"
    
    for root in SEARCH_ROOTS:
        if root.exists():
            try:
                for match in root.rglob(pattern):
                    if match.is_file():
                        matches.append(str(match))
                    if len(matches) >= 10:  # cap results
                        break
            except PermissionError:
                pass
        if len(matches) >= 10:
            break
    
    if not matches:
        return f"No files found matching \'{filename}{extension}\'"
    return "Found files:\\n" + "\\n".join(matches)

@tool
def read_file(file_path: str) -> str:
    """
    Read and return the contents of a text file.
    Provide the full file path.
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return f"File not found: {file_path}"
        if path.stat().st_size > 50_000:  # 50KB limit
            return f"File too large to read (>{50}KB). Use a text editor."
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"Could not read file: {e}"

@tool
def write_file(file_path: str, content: str, mode: str = "write") -> str:
    """
    Write or append content to a file.
    mode: \'write\' (overwrite) or \'append\' (add to end)
    Example: write_file(\'C:/notes.txt\', \'Buy milk\', \'append\')
    """
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_mode = "a" if mode == "append" else "w"
        with open(path, file_mode, encoding="utf-8") as f:
            f.write(content + "\\n")
        action = "Appended to" if mode == "append" else "Written to"
        return f"{action} {file_path} successfully."
    except Exception as e:
        return f"Could not write file: {e}"

@tool
def delete_file(file_path: str) -> str:
    """
    Delete a file permanently. Use with caution — this cannot be undone.
    Provide the full file path.
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return f"File not found: {file_path}"
        path.unlink()
        return f"Deleted {file_path} successfully."
    except Exception as e:
        return f"Could not delete file: {e}"

@tool
def list_directory(folder_path: str = "") -> str:
    """
    List files and folders in a directory.
    Defaults to Desktop if no path given.
    """
    path = Path(folder_path) if folder_path else Path.home() / "Desktop"
    try:
        if not path.exists():
            return f"Directory not found: {folder_path}"
        items = list(path.iterdir())
        files   = [f"📄 {i.name}" for i in items if i.is_file()]
        folders = [f"📁 {i.name}" for i in items if i.is_dir()]
        result  = folders + files
        return f"Contents of {path}:\\n" + "\\n".join(result[:20])
    except PermissionError:
        return f"Permission denied: {folder_path}"

