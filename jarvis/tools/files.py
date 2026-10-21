"""File management tools with safety guards (trash-only delete, protected paths)."""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from jarvis.tools.actions import log_action

# ── protected paths ───────────────────────────────────────────────────────────

_PROTECTED = [
    Path.home() / ".config" / "hypr",
    Path.home() / ".ssh",
    Path.home() / ".gnupg",
    Path.home() / ".env",
    Path("/etc"),
    Path("/usr"),
    Path("/sys"),
    Path("/proc"),
    Path("/boot"),
    Path("/bin"),
    Path("/sbin"),
]

_CONFIRM_THRESHOLD = 3  # bulk ops on > this many items need confirmed=True


def _resolve(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _check_protected(p: Path) -> None:
    for guard in _PROTECTED:
        try:
            p.relative_to(guard)
            raise PermissionError(f"Protected path: {guard}. Operation refused.")
        except ValueError:
            pass


def _outside_home(p: Path) -> bool:
    try:
        p.relative_to(Path.home())
        return False
    except ValueError:
        return True


# ── find ─────────────────────────────────────────────────────────────────────

def find_files(
    query: str,
    file_type: Optional[str] = None,
    max_results: int = 3,
    search_dir: str = "~",
) -> str:
    """
    Find files by name or content keyword. file_type: 'f' (file), 'd' (dir), or None.
    Returns top max_results paths.
    """
    base = Path(search_dir).expanduser()
    cmd = ["find", str(base), "-iname", f"*{query}*"]
    if file_type in ("f", "d"):
        cmd += ["-type", file_type]
    cmd += ["-not", "-path", "*/.*/*", "-maxdepth", "8"]

    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10
        ).stdout.splitlines()
    except subprocess.TimeoutExpired:
        return "Search timed out"

    results = out[:max_results]
    if not results:
        return f"No files matching '{query}' found"
    return "\n".join(results)


def recent_downloads(max_results: int = 5) -> str:
    dl = Path.home() / "Downloads"
    if not dl.exists():
        return "No Downloads folder"
    files = sorted(dl.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    lines = [f"{p.name} ({datetime.fromtimestamp(p.stat().st_mtime).strftime('%b %d %H:%M')})"
             for p in files[:max_results] if p.is_file()]
    return "\n".join(lines) or "Downloads folder is empty"


# ── open ─────────────────────────────────────────────────────────────────────

def open_path(path: str) -> str:
    p = _resolve(path)
    if not p.exists():
        return f"Not found: {path}"
    subprocess.Popen(["xdg-open", str(p)], start_new_session=True)
    return f"Opened {p.name}"


# ── move / copy / rename ──────────────────────────────────────────────────────

def move_file(src: str, dest: str, confirmed: bool = False) -> str:
    s, d = _resolve(src), _resolve(dest)
    _check_protected(s)
    if _outside_home(s) or _outside_home(d):
        if not confirmed:
            return f"CONFIRM_REQUIRED: Move '{s.name}' outside home? Say 'yes' to confirm."
    if not s.exists():
        return f"Not found: {src}"
    shutil.move(str(s), str(d))
    log_action("move", {"src": str(s), "dest": str(d)})
    return f"Moved {s.name} → {d}"


def copy_file(src: str, dest: str) -> str:
    s, d = _resolve(src), _resolve(dest)
    _check_protected(s)
    if not s.exists():
        return f"Not found: {src}"
    if s.is_dir():
        shutil.copytree(str(s), str(d))
    else:
        shutil.copy2(str(s), str(d))
    log_action("copy", {"src": str(s), "dest": str(d)})
    return f"Copied {s.name} → {d}"


def rename_file(path: str, new_name: str) -> str:
    p = _resolve(path)
    _check_protected(p)
    if not p.exists():
        return f"Not found: {path}"
    dest = p.parent / new_name
    if dest.exists():
        return f"Already exists: {new_name}"
    p.rename(dest)
    log_action("rename", {"src": str(p), "dest": str(dest)})
    return f"Renamed to {new_name}"


def make_directory(path: str) -> str:
    p = _resolve(path)
    _check_protected(p)
    p.mkdir(parents=True, exist_ok=True)
    log_action("mkdir", {"path": str(p)})
    return f"Created directory {p}"


# ── trash ─────────────────────────────────────────────────────────────────────

def trash_file(path: str, confirmed: bool = False) -> str:
    """Move a file to Trash. For >1 file pattern, requires confirmed=True."""
    p = _resolve(path)
    try:
        _check_protected(p)
    except PermissionError as e:
        return str(e)
    if not p.exists():
        return f"Not found: {path}"
    if not confirmed and _outside_home(p):
        return f"CONFIRM_REQUIRED: Trash '{p.name}' (outside home)? Say 'yes' to confirm."

    # prefer gio trash (gnome trash standard); fall back to trash-put
    for cmd in (["gio", "trash", str(p)], ["trash-put", str(p)]):
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=8)
            log_action("trash", {"path": str(p)})
            return f"Moved {p.name} to Trash"
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return f"Could not trash {p.name}: install gio or trash-cli"


def trash_files(paths: list[str], confirmed: bool = False) -> str:
    if len(paths) > _CONFIRM_THRESHOLD and not confirmed:
        return f"CONFIRM_REQUIRED: Trash {len(paths)} files? Say 'yes' to confirm."
    results = [trash_file(p, confirmed=True) for p in paths]
    return "; ".join(results)


# ── disk usage ────────────────────────────────────────────────────────────────

def disk_usage(path: str = "~") -> str:
    p = _resolve(path)
    try:
        stat = shutil.disk_usage(str(p))
        used = stat.used // (1024 ** 3)
        total = stat.total // (1024 ** 3)
        free = stat.free // (1024 ** 3)
        return f"Disk: {used}GB used / {total}GB total ({free}GB free)"
    except Exception as e:
        return f"Error: {e}"


# ── undo ─────────────────────────────────────────────────────────────────────

def undo_last_action() -> str:
    from jarvis.tools.actions import pop_last_action
    entry = pop_last_action()
    if not entry:
        return "Nothing to undo"

    action = entry.get("action")
    try:
        if action == "move":
            shutil.move(entry["dest"], entry["src"])
            return f"Undone: moved {Path(entry['dest']).name} back to {Path(entry['src']).parent}"
        elif action == "copy":
            d = Path(entry["dest"])
            if d.exists():
                if d.is_dir():
                    shutil.rmtree(str(d))
                else:
                    d.unlink()
            return f"Undone: removed copy at {d.name}"
        elif action == "rename":
            Path(entry["dest"]).rename(entry["src"])
            return f"Undone: renamed back to {Path(entry['src']).name}"
        elif action == "mkdir":
            p = Path(entry["path"])
            if p.exists() and not list(p.iterdir()):
                p.rmdir()
                return f"Undone: removed directory {p.name}"
            return f"Cannot undo mkdir: directory not empty or gone"
        else:
            return f"Cannot undo action: {action}"
    except Exception as e:
        return f"Undo failed: {e}"


# ── registration ──────────────────────────────────────────────────────────────

def register_file_tools(registry) -> None:
    P = {"type": "object", "properties": {}, "required": []}

    def _r(name, fn, desc, params=None):
        registry.add(name, fn, desc, params or P)

    _r("find_files", find_files,
       "Search for files or folders by name. Returns up to max_results paths.",
       {"type": "object",
        "properties": {
            "query": {"type": "string"},
            "file_type": {"type": "string", "enum": ["f", "d"]},
            "max_results": {"type": "integer", "default": 3},
            "search_dir": {"type": "string", "default": "~"},
        },
        "required": ["query"]})
    _r("recent_downloads", recent_downloads,
       "List the most recent files in ~/Downloads.",
       {"type": "object", "properties": {"max_results": {"type": "integer", "default": 5}}})
    _r("open_path", open_path,
       "Open a file or folder with the default application.",
       {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
    _r("move_file", move_file,
       "Move a file or folder. Requires confirmed=true if destination is outside home.",
       {"type": "object",
        "properties": {"src": {"type": "string"}, "dest": {"type": "string"},
                       "confirmed": {"type": "boolean", "default": False}},
        "required": ["src", "dest"]})
    _r("copy_file", copy_file,
       "Copy a file or directory.",
       {"type": "object",
        "properties": {"src": {"type": "string"}, "dest": {"type": "string"}},
        "required": ["src", "dest"]})
    _r("rename_file", rename_file,
       "Rename a file or folder.",
       {"type": "object",
        "properties": {"path": {"type": "string"}, "new_name": {"type": "string"}},
        "required": ["path", "new_name"]})
    _r("make_directory", make_directory,
       "Create a directory (including parents).",
       {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
    _r("trash_file", trash_file,
       "Move a file to Trash (never permanent delete). Requires confirmed=true if outside home.",
       {"type": "object",
        "properties": {"path": {"type": "string"}, "confirmed": {"type": "boolean", "default": False}},
        "required": ["path"]})
    _r("trash_files", trash_files,
       f"Trash multiple files. Requires confirmed=true if more than {_CONFIRM_THRESHOLD} files.",
       {"type": "object",
        "properties": {"paths": {"type": "array", "items": {"type": "string"}},
                       "confirmed": {"type": "boolean", "default": False}},
        "required": ["paths"]})
    _r("disk_usage", disk_usage,
       "Get disk usage for a path (defaults to home).",
       {"type": "object", "properties": {"path": {"type": "string", "default": "~"}}})
    _r("undo_last_action", undo_last_action,
       "Undo the last file operation (move/copy/rename/mkdir).")
