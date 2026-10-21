"""
Fast command dispatcher — intercepts obvious system commands before LLM.
Returns (handled: bool, result: str) where result is a short status string
that gets spoken/displayed. If not handled, caller falls through to Claude.
"""
from __future__ import annotations

import re
import asyncio
import subprocess
from typing import Optional


# ── matchers ─────────────────────────────────────────────────────────────────

def _num(text: str) -> Optional[int]:
    """Extract first integer from text, handling 'hundred' etc."""
    text = text.lower().replace("hundred", "100").replace("percent", "")
    m = re.search(r'\d+', text)
    return int(m.group()) if m else None


_FILLER = re.compile(r"^(?:(?:hey|ok|okay)\s+)?(?:jarvis\s+)?(?:(?:please|can you|could you)\s+)?")


def _normalize(text: str) -> str:
    t = re.sub(r"[^\w\s%]", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = _FILLER.sub("", t)
    return re.sub(r"\s+please$", "", t).strip()


async def _dispatch(text: str) -> Optional[str]:
    t = _normalize(text)

    # ── short aliases: "bright 50", "vol 30", "vol up", "lock" ───────────
    _short = re.match(r'^(bright|brightness|vol|volume)\s*(\d+)$', t)
    if _short:
        cmd, val = _short.group(1), int(_short.group(2))
        if cmd in ("bright", "brightness"):
            return await _set_brightness(val)
        return await _set_volume(val)

    if re.fullmatch(r"(lock|log|look)( (it|up|screen|the screen|my screen|pc|computer|laptop|the laptop|my laptop))?", t):
        return _lock()

    if t in ("mute", "unmute"):
        flag = "1" if t == "mute" else "0"
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", flag], capture_output=True)
        return "Muted." if t == "mute" else "Unmuted."

    if t in ("vol up", "volume up"):
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"], capture_output=True)
        return "Volume up."

    if t in ("vol down", "volume down"):
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"], capture_output=True)
        return "Volume down."

    # ── brightness ────────────────────────────────────────────────────────
    if any(w in t for w in ("brightness",)):
        if any(w in t for w in ("max", "full", "hundred", "100")):
            return await _set_brightness(100)
        if any(w in t for w in ("min", "zero", "off", "lowest")):
            return await _set_brightness(0)
        if any(w in t for w in ("up", "increase", "raise", "higher", "brighter")):
            cur = _get_brightness_val()
            return await _set_brightness(min(100, cur + 20))
        if any(w in t for w in ("down", "decrease", "lower", "dim", "darker")):
            cur = _get_brightness_val()
            return await _set_brightness(max(0, cur - 20))
        n = _num(t)
        if n is not None:
            return await _set_brightness(n)

    # ── volume ────────────────────────────────────────────────────────────
    if any(w in t for w in ("volume", "sound")):
        if any(w in t for w in ("mute", "silence", "quiet")):
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], capture_output=True)
            return "Muted."
        if any(w in t for w in ("unmute",)):
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], capture_output=True)
            return "Unmuted."
        if any(w in t for w in ("max", "full", "hundred", "100")):
            return await _set_volume(100)
        if any(w in t for w in ("up", "increase", "raise", "louder", "higher")):
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"], capture_output=True)
            return "Volume up."
        if any(w in t for w in ("down", "decrease", "lower", "quieter", "softer")):
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"], capture_output=True)
            return "Volume down."
        n = _num(t)
        if n is not None:
            return await _set_volume(n)

    # ── open apps ────────────────────────────────────────────────────────
    m = re.match(r"^(?:open|launch|start|run)\s+(?:the\s+|my\s+)?(.+?)(?:\s+app)?$", t)
    if m:
        return _open_app(m.group(1))

    # ── screenshot ───────────────────────────────────────────────────────
    if "screenshot" in t:
        subprocess.Popen(["grimblast", "copy", "screen"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Screenshot taken."

    # ── lock / sleep ─────────────────────────────────────────────────────
    if re.search(r"\b(lock|log|look)\b", t) and any(w in t for w in ("screen", "computer", "laptop", " pc")):
        return _lock()

    return None  # not handled — fall through to Claude


_APP_ALIASES = {
    "browser": "brave", "web browser": "brave", "internet": "brave",
    "files": "nautilus", "file manager": "nautilus",
    "code": "visual studio code", "vs code": "visual studio code", "vscode": "visual studio code",
}


def _desktop_apps() -> dict[str, str]:
    """Map lowercase app name / desktop id -> desktop id, from installed .desktop files."""
    import os
    from pathlib import Path
    dirs = [Path.home() / ".local/share/applications", Path("/usr/share/applications"),
            Path("/var/lib/flatpak/exports/share/applications")]
    apps: dict[str, str] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.glob("*.desktop"):
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            entry = text.split("[Desktop Action")[0]
            if re.search(r"^NoDisplay=true", entry, re.M):
                continue
            name = re.search(r"^Name=(.+)$", entry, re.M)
            if name:
                apps.setdefault(name.group(1).strip().lower(), f.name)
            apps.setdefault(f.stem.lower(), f.name)
    return apps


def _open_app(query: str) -> Optional[str]:
    q = _APP_ALIASES.get(query, query)
    if q in ("terminal", "a terminal"):
        subprocess.Popen(["uwsm", "app", "--", "xdg-terminal-exec"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Opening terminal."
    apps = _desktop_apps()
    desktop = apps.get(q)
    if not desktop:
        hits = sorted((n for n in apps if q in n), key=len)
        desktop = apps[hits[0]] if hits else None
    if not desktop:
        return None  # unknown app: let Claude answer
    subprocess.Popen(["uwsm", "app", "--", desktop], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Opening {query}."


def _lock() -> str:
    """Pause all media (incl. browser videos via MPRIS), lock silently."""
    subprocess.run(["playerctl", "-a", "pause"], capture_output=True)
    subprocess.Popen(["omarchy-system-lock"], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ""


async def _set_brightness(pct: int) -> str:
    try:
        from jarvis.tools.system import register_system_tools
        from jarvis.tools.registry import ToolRegistry
        r = ToolRegistry(); register_system_tools(r)
        result = await r.execute(
            __import__('jarvis.core.models', fromlist=['ToolCallRequest'])
            .ToolCallRequest(id='d', name='set_brightness', arguments={'percent': pct})
        )
        return f"Brightness set to {pct}%."
    except Exception:
        # fallback: brightnessctl
        subprocess.run(["brightnessctl", "set", f"{pct}%"], capture_output=True)
        return f"Brightness set to {pct}%."


def _get_brightness_val() -> int:
    try:
        r = subprocess.run(["brightnessctl", "get"], capture_output=True, text=True)
        cur = int(r.stdout.strip())
        r2 = subprocess.run(["brightnessctl", "max"], capture_output=True, text=True)
        max_v = int(r2.stdout.strip())
        return int(cur / max_v * 100)
    except Exception:
        return 50


async def _set_volume(pct: int) -> str:
    subprocess.run(
        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%"],
        capture_output=True,
    )
    return f"Volume set to {pct}%."


async def dispatch(text: str) -> Optional[str]:
    """Public entry. Returns short reply string or None if not a system command."""
    try:
        return await _dispatch(text)
    except Exception as e:
        return f"Command failed: {e}"
