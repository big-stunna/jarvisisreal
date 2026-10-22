"""
Audio feedback chimes. Generates WAV files on first use if missing.
Plays via paplay/afplay (non-blocking).
"""
from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger("jarvis.chimes")

_SOUNDS_DIR = Path(__file__).parent.parent.parent / "assets" / "sounds"
_RATE = 44100


def _sine(freq: float, duration: float, volume: float = 0.4) -> np.ndarray:
    t = np.linspace(0, duration, int(_RATE * duration), endpoint=False)
    wave = volume * np.sin(2 * np.pi * freq * t)
    # fade in/out 10ms
    fade = int(_RATE * 0.01)
    wave[:fade] *= np.linspace(0, 1, fade)
    wave[-fade:] *= np.linspace(1, 0, fade)
    return (wave * 32767).astype(np.int16)


def _write_wav(path: Path, data: np.ndarray) -> None:
    import wave, struct
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_RATE)
        wf.writeframes(data.tobytes())


def _ensure_sounds() -> None:
    _SOUNDS_DIR.mkdir(parents=True, exist_ok=True)

    on_path  = _SOUNDS_DIR / "on.wav"
    off_path = _SOUNDS_DIR / "off.wav"

    if not on_path.exists():
        # rising two-tone: C5 → E5
        chunk = np.concatenate([_sine(523.25, 0.12), _sine(659.25, 0.15)])
        _write_wav(on_path, chunk)

    if not off_path.exists():
        # falling two-tone: E5 → C5
        chunk = np.concatenate([_sine(659.25, 0.12), _sine(523.25, 0.15)])
        _write_wav(off_path, chunk)


def _play(path: Path) -> None:
    try:
        from jarvis.osctl import play_cmd
        subprocess.Popen(
            play_cmd(str(path)),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        log.debug("Chime play error: %s", e)


def play_on() -> None:
    _ensure_sounds()
    threading.Thread(target=_play, args=(_SOUNDS_DIR / "on.wav",), daemon=True).start()


def play_off() -> None:
    _ensure_sounds()
    threading.Thread(target=_play, args=(_SOUNDS_DIR / "off.wav",), daemon=True).start()
