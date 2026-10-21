"""Everyday tools: timers, weather, media, time, calculate."""
from __future__ import annotations

import ast
import math
import operator
import re
import subprocess
import threading
from datetime import datetime
from typing import Optional

# ── timers & reminders ────────────────────────────────────────────────────────

_active_timers: dict[str, threading.Timer] = {}


def _notify(title: str, body: str = "") -> None:
    try:
        subprocess.run(["notify-send", "-u", "normal", title, body],
                       capture_output=True, timeout=5)
    except Exception:
        pass


def set_timer(seconds: int, label: str = "Timer") -> str:
    if seconds <= 0:
        return "Timer must be positive seconds"
    label_key = label.lower()

    def _fire():
        _active_timers.pop(label_key, None)
        _notify(f"⏱ {label}", "Time's up!")

    t = threading.Timer(seconds, _fire)
    t.daemon = True
    t.start()
    _active_timers[label_key] = t

    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    parts = []
    if hrs:  parts.append(f"{hrs}h")
    if mins: parts.append(f"{mins}m")
    if secs: parts.append(f"{secs}s")
    return f"Timer set: {label} in {' '.join(parts)}"


def cancel_timer(label: str = "Timer") -> str:
    key = label.lower()
    t = _active_timers.pop(key, None)
    if t:
        t.cancel()
        return f"Timer '{label}' cancelled"
    return f"No active timer named '{label}'"


def list_timers() -> str:
    if not _active_timers:
        return "No active timers"
    return "Active timers: " + ", ".join(_active_timers.keys())


def set_reminder(delay_minutes: int, message: str) -> str:
    return set_timer(delay_minutes * 60, label=f"Reminder: {message}")


# ── weather ───────────────────────────────────────────────────────────────────

def get_weather(location: str = "") -> str:
    """Fetch weather from wttr.in (no API key, text format)."""
    import urllib.request
    loc = location.replace(" ", "+") or ""
    url = f"https://wttr.in/{loc}?format=3"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return resp.read().decode().strip()
    except Exception as e:
        return f"Weather unavailable: {e}"


# ── media ─────────────────────────────────────────────────────────────────────

def _playerctl(*args: str) -> str:
    r = subprocess.run(["playerctl", *args], capture_output=True, text=True, timeout=5)
    return r.stdout.strip()


def media_status() -> str:
    title  = _playerctl("metadata", "title")
    artist = _playerctl("metadata", "artist")
    status = _playerctl("status")
    if not title:
        return "Nothing playing"
    parts = [title]
    if artist:
        parts.append(f"by {artist}")
    if status:
        parts.append(f"({status.lower()})")
    return " ".join(parts)


def media_play_pause() -> str:
    _playerctl("play-pause")
    return media_status()


def media_next() -> str:
    _playerctl("next")
    return "Skipped to next track"


def media_previous() -> str:
    _playerctl("previous")
    return "Previous track"


def media_stop() -> str:
    _playerctl("stop")
    return "Playback stopped"


def media_volume(percent: int) -> str:
    level = max(0, min(100, percent)) / 100
    _playerctl("volume", f"{level:.2f}")
    return f"Media volume set to {percent}%"


# ── time ──────────────────────────────────────────────────────────────────────

def get_time(timezone: Optional[str] = None) -> str:
    if timezone:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(timezone))
            return now.strftime(f"%I:%M %p %Z (%A %d %B)")
        except Exception:
            return f"Unknown timezone: {timezone}"
    now = datetime.now()
    return now.strftime("%I:%M %p (%A %d %B %Y)")


def get_date() -> str:
    return datetime.now().strftime("%A, %d %B %Y")


# ── calculate ─────────────────────────────────────────────────────────────────

_SAFE_NAMES = {
    k: getattr(math, k) for k in dir(math) if not k.startswith("_")
}
_SAFE_NAMES.update({"abs": abs, "round": round, "int": int, "float": float})

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Name, ast.Load,
)


def _safe_eval(expr: str) -> float:
    tree = ast.parse(expr.strip(), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"Unsafe expression: {type(node).__name__}")
    code = compile(tree, "<calc>", "eval")
    return eval(code, {"__builtins__": {}}, _SAFE_NAMES)  # noqa: S307


def calculate(expression: str) -> str:
    # Convert common verbal forms: "2 to the power of 8" → "2**8"
    expr = expression
    expr = re.sub(r"to the power of\s+(\d+)", r"**\1", expr, flags=re.I)
    expr = re.sub(r"squared", "**2", expr, flags=re.I)
    expr = re.sub(r"cubed",   "**3", expr, flags=re.I)
    expr = re.sub(r"√\s*",    "sqrt(", expr)
    expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**")
    try:
        result = _safe_eval(expr)
        if isinstance(result, float) and result.is_integer():
            return str(int(result))
        return f"{result:.6g}"
    except Exception as e:
        return f"Could not evaluate '{expression}': {e}"


# ── registration ──────────────────────────────────────────────────────────────

def register_everyday_tools(registry) -> None:
    P = {"type": "object", "properties": {}, "required": []}

    def _r(name, fn, desc, params=None):
        registry.add(name, fn, desc, params or P)

    _r("set_timer", set_timer,
       "Set a countdown timer. Fires a desktop notification when done.",
       {"type": "object",
        "properties": {"seconds": {"type": "integer"}, "label": {"type": "string", "default": "Timer"}},
        "required": ["seconds"]})
    _r("cancel_timer", cancel_timer,
       "Cancel a named timer.",
       {"type": "object", "properties": {"label": {"type": "string", "default": "Timer"}}})
    _r("list_timers", list_timers, "List all currently active timers.")
    _r("set_reminder", set_reminder,
       "Set a reminder to fire in N minutes with a message.",
       {"type": "object",
        "properties": {"delay_minutes": {"type": "integer"}, "message": {"type": "string"}},
        "required": ["delay_minutes", "message"]})
    _r("get_weather", get_weather,
       "Get current weather for a location (or auto-detect if empty). Uses wttr.in, no API key needed.",
       {"type": "object", "properties": {"location": {"type": "string", "default": ""}}})
    _r("media_status",     media_status,     "Get currently playing track and status.")
    _r("media_play_pause", media_play_pause, "Toggle play/pause for media.")
    _r("media_next",       media_next,       "Skip to the next track.")
    _r("media_previous",   media_previous,   "Go to the previous track.")
    _r("media_stop",       media_stop,       "Stop media playback.")
    _r("media_volume", media_volume,
       "Set media player volume (0-100).",
       {"type": "object", "properties": {"percent": {"type": "integer"}}, "required": ["percent"]})
    _r("get_time", get_time,
       "Get the current time, optionally in a given IANA timezone (e.g. 'America/New_York').",
       {"type": "object", "properties": {"timezone": {"type": "string"}}})
    _r("get_date", get_date, "Get today's date.")
    _r("calculate", calculate,
       "Evaluate a maths expression safely. Supports +−×÷^, sqrt, sin, cos, log, etc.",
       {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]})
