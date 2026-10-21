"""Window management and app-launching tools via hyprctl."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def _hyprctl(*args: str) -> str:
    r = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=8)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "hyprctl failed")
    return r.stdout


def _dispatch(*args: str) -> str:
    _hyprctl("dispatch", *args)
    return "ok"


# ── apps ──────────────────────────────────────────────────────────────────────

def open_app(app: str, workspace: int | None = None) -> str:
    if workspace is not None:
        _dispatch("workspace", str(workspace))
    subprocess.Popen([app], start_new_session=True)
    return f"Opened {app}" + (f" on workspace {workspace}" if workspace else "")


# ── windows ───────────────────────────────────────────────────────────────────

def list_windows(workspace_id: int | None = None) -> str:
    data: list[dict[str, Any]] = json.loads(_hyprctl("clients", "-j"))
    if workspace_id is not None:
        data = [w for w in data if w.get("workspace", {}).get("id") == workspace_id]
    if not data:
        return "No windows found"
    lines = [f"{w.get('title', '?')} [{w.get('class', '?')}]" for w in data[:10]]
    return "\n".join(lines)


def close_window(confirmed: bool = False) -> str:
    if not confirmed:
        win = json.loads(_hyprctl("activewindow", "-j"))
        title = win.get("title", "this window")
        return f"CONFIRM_REQUIRED: Close '{title}'? Say 'yes' to confirm."
    _dispatch("killactive")
    return "Window closed"


def fullscreen_window(mode: int = 1) -> str:
    """mode: 0=real fullscreen, 1=maximize, 2=fullscreen no-gaps"""
    _dispatch("fullscreen", str(mode))
    return "Fullscreen toggled"


def toggle_floating() -> str:
    _dispatch("togglefloating")
    return "Float toggled"


def move_window_to_workspace(workspace_id: int) -> str:
    _dispatch("movetoworkspace", str(workspace_id))
    return f"Window moved to workspace {workspace_id}"


def switch_workspace(workspace_id: int) -> str:
    _dispatch("workspace", str(workspace_id))
    return f"Switched to workspace {workspace_id}"


def get_active_window() -> str:
    w = json.loads(_hyprctl("activewindow", "-j"))
    return f"{w.get('title', '?')} [{w.get('class', '?')}]"


def get_active_workspace() -> str:
    ws = json.loads(_hyprctl("activeworkspace", "-j"))
    return f"Workspace {ws.get('id')} — {ws.get('name', '')}"


# ── theme & wallpaper ─────────────────────────────────────────────────────────

def list_themes() -> str:
    theme_dir = Path.home() / ".config" / "omarchy" / "themes"
    if not theme_dir.exists():
        return "No themes directory found"
    names = sorted(p.name for p in theme_dir.iterdir() if p.is_dir())
    return "\n".join(names) or "No themes found"


def set_theme(name: str) -> str:
    script = Path.home() / ".local" / "share" / "omarchy" / "bin" / "omarchy-set-theme"
    if not script.exists():
        # try PATH
        result = subprocess.run(
            ["omarchy-set-theme", name], capture_output=True, text=True, timeout=15
        )
    else:
        result = subprocess.run(
            [str(script), name], capture_output=True, text=True, timeout=15
        )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Theme change failed")
    return f"Theme changed to {name}"


def set_wallpaper(path: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"File not found: {path}"
    subprocess.Popen(
        ["hyprctl", "hyprpaper", "wallpaper", f",{p}"],
        start_new_session=True,
    )
    return f"Wallpaper set to {p.name}"


# ── registration ──────────────────────────────────────────────────────────────

def register_window_tools(registry) -> None:
    P = {"type": "object", "properties": {}, "required": []}

    def _r(name, fn, desc, params=None):
        registry.add(name, fn, desc, params or P)

    _r("open_app", open_app, "Open an application by its executable name, optionally on a workspace.",
       {"type": "object",
        "properties": {"app": {"type": "string"}, "workspace": {"type": "integer"}},
        "required": ["app"]})
    _r("list_windows", list_windows, "List open windows, optionally filtered by workspace id.",
       {"type": "object", "properties": {"workspace_id": {"type": "integer"}}})
    _r("close_window", close_window, "Close the focused window. Requires confirmed=true after user says yes.",
       {"type": "object", "properties": {"confirmed": {"type": "boolean", "default": False}}})
    _r("fullscreen_window", fullscreen_window, "Toggle fullscreen on the focused window.",
       {"type": "object", "properties": {"mode": {"type": "integer", "default": 1}}})
    _r("toggle_floating", toggle_floating, "Toggle floating mode on the focused window.")
    _r("move_window_to_workspace", move_window_to_workspace, "Move focused window to a workspace.",
       {"type": "object", "properties": {"workspace_id": {"type": "integer"}}, "required": ["workspace_id"]})
    _r("switch_workspace", switch_workspace, "Switch to a workspace by id.",
       {"type": "object", "properties": {"workspace_id": {"type": "integer"}}, "required": ["workspace_id"]})
    _r("get_active_window",    get_active_window,    "Get the focused window's title and class.")
    _r("get_active_workspace", get_active_workspace, "Get the currently focused workspace.")
    _r("list_themes",  list_themes,  "List available Omarchy themes.")
    _r("set_theme",    set_theme,    "Switch to an Omarchy theme by name.",
       {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})
    _r("set_wallpaper", set_wallpaper, "Set wallpaper to a given file path.",
       {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
