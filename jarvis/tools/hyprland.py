"""Hyprland IPC tools via the `hyprctl` CLI (JSON mode)."""
import json
import subprocess
from typing import Any, Dict, List


def _hyprctl(*args: str) -> str:
    result = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "hyprctl failed")
    return result.stdout


def get_active_workspace() -> Dict[str, Any]:
    return json.loads(_hyprctl("activeworkspace", "-j"))


def get_active_window() -> Dict[str, Any]:
    return json.loads(_hyprctl("activewindow", "-j"))


def list_workspaces() -> List[Dict[str, Any]]:
    return json.loads(_hyprctl("workspaces", "-j"))


def switch_workspace(workspace_id: int) -> str:
    _hyprctl("dispatch", "workspace", str(workspace_id))
    return f"Switched to workspace {workspace_id}"


def move_window_to_workspace(workspace_id: int) -> str:
    _hyprctl("dispatch", "movetoworkspace", str(workspace_id))
    return f"Moved active window to workspace {workspace_id}"


def register_hyprland_tools(registry) -> None:
    registry.add(
        "get_active_workspace", get_active_workspace,
        "Get the currently focused Hyprland workspace.",
    )
    registry.add(
        "get_active_window", get_active_window,
        "Get the currently focused window's title and class.",
    )
    registry.add(
        "list_workspaces", list_workspaces,
        "List all Hyprland workspaces across monitors.",
    )
    registry.add(
        "switch_workspace", switch_workspace,
        "Switch focus to a given workspace by id.",
        {"type": "object", "properties": {"workspace_id": {"type": "integer"}}, "required": ["workspace_id"]},
    )
    registry.add(
        "move_window_to_workspace", move_window_to_workspace,
        "Move the focused window to a given workspace by id.",
        {"type": "object", "properties": {"workspace_id": {"type": "integer"}}, "required": ["workspace_id"]},
    )
