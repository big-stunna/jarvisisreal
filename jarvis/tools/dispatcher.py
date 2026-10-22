"""
Fast command dispatcher — handles system commands locally before any LLM call.
Returns a short reply string, "" for silent actions, or None to fall through to the LLM.
"""
from __future__ import annotations

import re
from typing import Optional

from jarvis import osctl


def _num(text: str) -> Optional[int]:
    text = text.lower().replace("hundred", "100").replace("percent", "")
    m = re.search(r'\d+', text)
    return int(m.group()) if m else None


_FILLER = re.compile(r"^(?:(?:hey|ok|okay)\s+)?(?:jarvis\s+)?(?:(?:please|can you|could you)\s+)?")


def _normalize(text: str) -> str:
    t = re.sub(r"[^\w\s%]", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = _FILLER.sub("", t)
    return re.sub(r"\s+please$", "", t).strip()


def _lock() -> str:
    osctl.pause_media()
    osctl.lock_screen()
    return ""


def _brightness(pct: int) -> str:
    pct = max(0, min(100, pct))
    if not osctl.set_brightness(pct):
        return "Brightness control isn't set up. Run: brew install brightness"
    return f"Brightness set to {pct}%."


def _volume(pct: int) -> str:
    pct = max(0, min(100, pct))
    osctl.set_volume(pct)
    return f"Volume set to {pct}%."


def _mute(muted: bool) -> str:
    osctl.set_mute(muted)
    return "Muted." if muted else "Unmuted."


def _vol_step(delta: int) -> str:
    osctl.change_volume(delta)
    return "Volume up." if delta > 0 else "Volume down."


async def _dispatch(text: str) -> Optional[str]:
    t = _normalize(text)

    short = re.match(r'^(bright|brightness|vol|volume)\s*(\d+)$', t)
    if short:
        val = int(short.group(2))
        return _brightness(val) if short.group(1).startswith("bright") else _volume(val)

    if re.fullmatch(r"(lock|log|look)( (it|up|screen|the screen|my screen|pc|computer|laptop|the laptop|my laptop|mac|my mac))?", t):
        return _lock()

    if t in ("mute", "unmute"):
        return _mute(t == "mute")
    if t in ("vol up", "volume up"):
        return _vol_step(10)
    if t in ("vol down", "volume down"):
        return _vol_step(-10)

    if "brightness" in t:
        if any(w in t for w in ("max", "full", "hundred", "100")):
            return _brightness(100)
        if any(w in t for w in ("min", "zero", "off", "lowest")):
            return _brightness(0)
        if any(w in t for w in ("up", "increase", "raise", "higher", "brighter")):
            return _brightness(osctl.get_brightness() + 20)
        if any(w in t for w in ("down", "decrease", "lower", "dim", "darker")):
            return _brightness(osctl.get_brightness() - 20)
        n = _num(t)
        if n is not None:
            return _brightness(n)

    if any(w in t for w in ("volume", "sound")):
        if "unmute" in t:
            return _mute(False)
        if any(w in t for w in ("mute", "silence", "quiet")):
            return _mute(True)
        if any(w in t for w in ("max", "full", "hundred", "100")):
            return _volume(100)
        if any(w in t for w in ("up", "increase", "raise", "louder", "higher")):
            return _vol_step(10)
        if any(w in t for w in ("down", "decrease", "lower", "quieter", "softer")):
            return _vol_step(-10)
        n = _num(t)
        if n is not None:
            return _volume(n)

    m = re.match(r"^(?:open|launch|start|run)\s+(?:the\s+|my\s+)?(.+?)(?:\s+app)?$", t)
    if m:
        return osctl.open_app(m.group(1))

    if "screenshot" in t:
        osctl.screenshot()
        return "Screenshot taken."

    if re.search(r"\b(lock|log|look)\b", t) and any(w in t for w in ("screen", "computer", "laptop", " pc", " mac")):
        return _lock()

    return None


async def dispatch(text: str) -> Optional[str]:
    """Public entry. Returns short reply string or None if not a system command."""
    try:
        return await _dispatch(text)
    except Exception as e:
        return f"Command failed: {e}"
