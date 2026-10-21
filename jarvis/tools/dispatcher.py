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


async def _dispatch(text: str) -> Optional[str]:
    t = text.lower().strip()

    # ── short aliases: "bright 50", "vol 30", "vol up", "lock" ───────────
    _short = re.match(r'^(bright|brightness|vol|volume)\s*(\d+)$', t)
    if _short:
        cmd, val = _short.group(1), int(_short.group(2))
        if cmd in ("bright", "brightness"):
            return await _set_brightness(val)
        return await _set_volume(val)

    if t in ("lock", "lock screen", "lock pc"):
        subprocess.Popen(["hyprlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Locking screen."

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
    app_map = {
        "spotify": "spotify",
        "firefox": "firefox",
        "chrome": "google-chrome-stable",
        "browser": "xdg-open https://",
        "terminal": "xdg-terminal-exec",
        "files": "nautilus",
        "file manager": "nautilus",
        "obsidian": "obsidian",
        "discord": "discord",
        "telegram": "telegram-desktop",
        "signal": "signal-desktop",
        "code": "code",
        "vscode": "code",
        "settings": "gnome-control-center",
    }
    if any(w in t for w in ("open", "launch", "start", "run")):
        for keyword, cmd in app_map.items():
            if keyword in t:
                try:
                    subprocess.Popen(cmd.split(), start_new_session=True,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return f"Opening {keyword}."
                except FileNotFoundError:
                    return f"{keyword} doesn't seem to be installed."

    # ── screenshot ───────────────────────────────────────────────────────
    if "screenshot" in t:
        subprocess.Popen(["grimblast", "copy", "screen"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Screenshot taken."

    # ── lock / sleep ─────────────────────────────────────────────────────
    if "lock" in t and ("screen" in t or "computer" in t or t == "lock"):
        subprocess.Popen(["hyprlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Locking screen."

    return None  # not handled — fall through to Claude


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
