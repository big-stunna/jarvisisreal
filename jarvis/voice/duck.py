"""Audio ducking: lower media volume during listening/speaking, then restore."""
from __future__ import annotations

import subprocess
from contextlib import contextmanager


def _wpctl(args: list[str]) -> None:
    try:
        subprocess.run(["wpctl", *args], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass  # no wpctl or pipewire — skip silently


def _playerctl(args: list[str]) -> None:
    try:
        subprocess.run(["playerctl", *args], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass


def get_sink_volume() -> float:
    """Return current default sink volume (0.0–1.0), or 1.0 on error."""
    try:
        out = subprocess.check_output(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], text=True
        )
        # "Volume: 0.80" or "Volume: 0.80 [MUTED]"
        return float(out.split()[1])
    except Exception:
        return 1.0


def set_sink_volume(level: float) -> None:
    _wpctl(["set-volume", "@DEFAULT_AUDIO_SINK@", f"{level:.2f}"])


@contextmanager
def ducked(target_volume: float = 0.2):
    """Context manager: lower sink volume to target_volume, restore on exit."""
    original = get_sink_volume()
    ducked_level = min(original, target_volume)
    set_sink_volume(ducked_level)
    try:
        yield
    finally:
        set_sink_volume(original)
