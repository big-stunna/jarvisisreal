"""OS-specific actions (Linux/Hyprland and macOS) behind one interface."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

IS_MAC = sys.platform == "darwin"

_QUIET = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _run(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True)


def _spawn(*cmd: str) -> None:
    subprocess.Popen(list(cmd), start_new_session=True, **_QUIET)


def _osa(script: str) -> str:
    return _run("osascript", "-e", script).stdout.strip()


# ── audio ────────────────────────────────────────────────────────────────────

MIC_DEVICE = None if IS_MAC else "pulse"


def mic_device():
    """Input device for Jarvis: the built-in mic, so Bluetooth earbuds stay in
    A2DP (music) mode instead of dropping to HFP (call) mode. Override with
    JARVIS_MIC (a device name substring on macOS, a PulseAudio source on Linux)."""
    want = os.environ.get("JARVIS_MIC", "")
    if IS_MAC:
        import sounddevice as sd
        keys = [want] if want else ["MacBook", "Built-in"]
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and any(k.lower() in d["name"].lower() for k in keys):
                return i
        return None
    src = want
    if not src:
        out = _run("pactl", "list", "short", "sources").stdout.splitlines()
        names = [l.split("\t")[1] for l in out if "\t" in l]
        builtin = [n for n in names if n.startswith("alsa_input.")]
        src = next((n for n in builtin if "Mic1" in n), builtin[0] if builtin else "")
    if src:
        os.environ["PULSE_SOURCE"] = src  # read by PortAudio's pulse device on open
    return MIC_DEVICE


def play_cmd(path: str) -> list[str]:
    """Command that plays an audio file (wav/mp3) and exits when done."""
    return ["afplay", path] if IS_MAC else ["paplay", path]


def set_volume(pct: int) -> None:
    pct = max(0, min(100, pct))
    if IS_MAC:
        _osa(f"set volume output volume {pct}")
    else:
        _run("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%")


def change_volume(delta: int) -> None:
    if IS_MAC:
        cur = int(_osa("output volume of (get volume settings)") or 50)
        set_volume(cur + delta)
    else:
        _run("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{delta:+d}%")


def set_mute(muted: bool) -> None:
    if IS_MAC:
        _osa(f"set volume output muted {'true' if muted else 'false'}")
    else:
        _run("pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0")


def pause_media() -> None:
    if IS_MAC:
        for app in ("Music", "Spotify"):
            _osa(f'if application "{app}" is running then tell application "{app}" to pause')
    else:
        _run("playerctl", "-a", "pause")


# ── display ──────────────────────────────────────────────────────────────────

def set_brightness(pct: int) -> bool:
    pct = max(0, min(100, pct))
    if IS_MAC:
        if not shutil.which("brightness"):
            return False
        _run("brightness", f"{pct / 100:.2f}")
        return True
    _run("brightnessctl", "set", f"{pct}%")
    return True


def get_brightness() -> int:
    try:
        if IS_MAC:
            out = _run("brightness", "-l").stdout
            m = re.search(r"brightness\s+([\d.]+)", out)
            return int(float(m.group(1)) * 100) if m else 50
        cur = int(_run("brightnessctl", "get").stdout.strip())
        mx = int(_run("brightnessctl", "max").stdout.strip())
        return int(cur / mx * 100)
    except Exception:
        return 50


def lock_screen() -> None:
    if IS_MAC:
        _spawn("pmset", "displaysleepnow")
    else:
        _spawn("omarchy-system-lock" if shutil.which("omarchy-system-lock") else "hyprlock")


def screen_locked() -> bool:
    if IS_MAC:
        try:
            import Quartz  # pyobjc-framework-Quartz
            d = Quartz.CGSessionCopyCurrentDictionary() or {}
            return bool(d.get("CGSSessionScreenIsLocked", 0))
        except Exception:
            return False
    return _run("pgrep", "-x", "hyprlock").returncode == 0


def screenshot() -> None:
    if IS_MAC:
        _spawn("screencapture", "-c")
    else:
        _spawn("grimblast", "copy", "screen")


def notify(title: str, body: str) -> None:
    if IS_MAC:
        _osa(f'display notification "{body}" with title "{title}"')
    else:
        _spawn("notify-send", "-t", "1500", title, body)


# ── apps ─────────────────────────────────────────────────────────────────────

_ALIASES_LINUX = {
    "browser": "brave", "web browser": "brave", "internet": "brave",
    "files": "nautilus", "file manager": "nautilus",
    "code": "visual studio code", "vs code": "visual studio code", "vscode": "visual studio code",
}
_ALIASES_MAC = {
    "browser": "safari", "web browser": "safari", "internet": "safari",
    "files": "finder", "file manager": "finder", "terminal": "terminal",
    "code": "visual studio code", "vs code": "visual studio code", "vscode": "visual studio code",
    "settings": "system settings",
}


def _mac_apps() -> dict[str, str]:
    apps: dict[str, str] = {}
    for d in ("/Applications", "/System/Applications", "/System/Applications/Utilities",
              str(Path.home() / "Applications")):
        p = Path(d)
        if p.is_dir():
            for a in p.glob("*.app"):
                apps.setdefault(a.stem.lower(), a.stem)
    return apps


def _linux_apps() -> dict[str, str]:
    dirs = [Path.home() / ".local/share/applications", Path("/usr/share/applications"),
            Path("/var/lib/flatpak/exports/share/applications")]
    apps: dict[str, str] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.glob("*.desktop"):
            try:
                entry = f.read_text(errors="ignore").split("[Desktop Action")[0]
            except OSError:
                continue
            if re.search(r"^NoDisplay=true", entry, re.M):
                continue
            name = re.search(r"^Name=(.+)$", entry, re.M)
            if name:
                apps.setdefault(name.group(1).strip().lower(), f.name)
            apps.setdefault(f.stem.lower(), f.name)
    return apps


def open_app(query: str) -> Optional[str]:
    """Launch an installed app by spoken name. Returns None if nothing matches."""
    q = (_ALIASES_MAC if IS_MAC else _ALIASES_LINUX).get(query, query)
    if not IS_MAC and q in ("terminal", "a terminal"):
        _spawn("uwsm", "app", "--", "xdg-terminal-exec")
        return "Opening terminal."
    apps = _mac_apps() if IS_MAC else _linux_apps()
    target = apps.get(q)
    if not target:
        hits = sorted((n for n in apps if q in n), key=len)
        target = apps[hits[0]] if hits else None
    if not target:
        return None
    if IS_MAC:
        _spawn("open", "-a", target)
    else:
        _spawn("uwsm", "app", "--", target)
    return f"Opening {query}."


# ── misc ─────────────────────────────────────────────────────────────────────

def runtime_dir() -> str:
    """Per-user dir for lock files: /run/user/<uid> on Linux, $TMPDIR on macOS."""
    if IS_MAC:
        return tempfile.gettempdir()
    return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
