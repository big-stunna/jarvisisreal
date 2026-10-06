"""LiveContext: gather light-weight desktop state (window, battery, RAM,
clipboard preview) for inclusion in multimodal queries.

Disabled by default (`context.live: true` in config) to avoid extra
subprocess calls and leaking unnecessary state.
"""
import json
import os
import subprocess
from typing import Any, Dict, List, Optional


def _active_window() -> Optional[str]:
    """Return the focused window's title, or None."""
    try:
        raw = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        if raw.stdout.strip():
            data = json.loads(raw.stdout)
            return data.get("title") or data.get("class")
    except (subprocess.CalledProcessError, json.JSONDecodeError,
            OSError, ValueError, TimeoutError):
        return None
    return None


def _battery_level() -> Optional[str]:
    """Return a short battery string like '72% (charging)' or None."""
    # Fallback 1: sysfs (most laptops)
    for path in ("/sys/class/power_supply/BAT0/capacity",
                 "/sys/class/power_supply/BAT0/charge_now",
                 "/sys/class/power_supply/BAT0/voltage_now"):
        if os.path.exists(path):
            try:
                val = open(path).read().strip()
                pct = int(val)
                status = ""
                if "charge_now" in path or "voltage_now" in path:
                    # derive status from charging now/voltage > 0
                    charger = path.replace("voltage_now", "type")
                    if os.path.exists(charger):
                        status = "(charging)" if "Charging" in open(charger).read() else ""
                    pct_txt = f"{val}% (DC)"
                else:
                    pct_txt = f"{pct}%"
                return f"{pct_txt} {status}".strip()
            except (OSError, ValueError):
                continue
    # Fallback 2: upower
    try:
        raw = subprocess.run(
            ["upower", "-i", "/org/freedesktop/UPower/devices/battery_BAT0"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        for line in raw.stdout.splitlines():
            if line.startswith("  percentage:"):
                return line.split(":", 1)[1].strip()
    except (subprocess.CalledProcessError, OSError):
        pass
    return None


def _ram_usage() -> Optional[str]:
    """Return a short RAM usage string, e.g. '7.2G / 16G used'."""
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                key = line.split(":")[0]
                val = int(line.split(":")[1].split()[0])  # kB
                mem[key] = val
        total_kb = mem.get("MemTotal", 0)
        free_kb = mem.get("MemFree", 0)
        buffers_kb = mem.get("Buffers", 0)
        cached_kb = mem.get("Cached", 0)
        used_kb = total_kb - free_kb - buffers_kb - cached_kb
        used_mb = used_kb / 1024
        total_mb = total_kb / 1024
        if total_mb >= 1024:
            return f"{used_mb/1024:.1f}G / {total_mb/1024:.1f}G used"
        return f"{used_mb:.0f}M / {total_mb:.0f}M used"
    except (OSError, ValueError, KeyError):
        return None


def _clipboard_preview() -> Optional[str]:
    """Return a short preview of the clipboard without holding it open."""
    try:
        out = subprocess.run(
            ["wl-paste", "--list-types"], capture_output=True, text=True,
            check=True, timeout=5,
        )
        mimes = out.stdout.splitlines()
        has_image = any(m.startswith("image/") for m in mimes)
        if has_image:
            return "[image in clipboard]"
        raw = subprocess.run(
            ["wl-paste", "-t", "text/plain"], capture_output=True, text=True,
            check=True, timeout=5,
        )
        text = raw.stdout.strip()
        if not text:
            return None
        preview = text[:200] + "..." if len(text) > 200 else text
        return f"[clipboard preview: {preview}]"
    except (subprocess.CalledProcessError, OSError):
        return None


class LiveContext:
    """Collect a snapshot of desktop state for vision queries."""

    def __init__(
        self,
        window: bool = True,
        battery: bool = True,
        ram: bool = True,
        clipboard: bool = True,
        timeout: float = 5.0,
    ):
        self.window = window
        self.battery = battery
        self.ram = ram
        self.clipboard = clipboard
        self.timeout = timeout

    def summary(self) -> Optional[str]:
        """Build a one-line summary string of gathered state."""
        parts: List[str] = []
        if self.window:
            w = _active_window()
            if w:
                parts.append(f"window: {w}")
        if self.battery:
            b = _battery_level()
            if b:
                parts.append(f"battery: {b}")
        if self.ram:
            r = _ram_usage()
            if r:
                parts.append(f"memory: {r}")
        if self.clipboard:
            c = _clipboard_preview()
            if c:
                parts.append(c)
        return " | ".join(parts) if parts else None

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> Optional["LiveContext"]:
        """Build from `context.live` config key. Returns None if disabled."""
        ctx_cfg = config.get("context", {}) or {}
        if not ctx_cfg.get("live"):
            return None
        return cls(
            window=ctx_cfg.get("window", True),
            battery=ctx_cfg.get("battery", True),
            ram=ctx_cfg.get("ram", True),
            clipboard=ctx_cfg.get("clipboard", True),
        )
