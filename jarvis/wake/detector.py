"""
Wake word detector using openWakeWord.
Listens on the mic continuously at low sample rate.
Calls on_wake() when "hey jarvis" (or configured word) is detected.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("jarvis.wake")

_CHUNK = 1280        # 80 ms at 16kHz — required by openWakeWord
_RATE  = 16000
_MODEL = "hey_jarvis"   # bundled openWakeWord model


class WakeWordDetector:
    """
    Runs in a background thread. Calls on_wake() from that thread
    when the wake word fires. Thread-safe stop via stop().
    """

    def __init__(
        self,
        on_wake: Callable[[], None],
        threshold: float = 0.35,
        model_name: str = _MODEL,
    ):
        self._on_wake = on_wake
        self._threshold = threshold
        self._model_name = model_name
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._oww = None
        self.paused = False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="jarvis-wake"
        )
        self._thread.start()
        log.info("Wake word detector started (model=%s, threshold=%.2f)",
                 self._model_name, self._threshold)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _load_model(self):
        import os, openwakeword
        from openwakeword.model import Model
        path = os.path.join(os.path.dirname(openwakeword.__file__),
                            "resources", "models", f"{self._model_name}_v0.1.onnx")
        return Model(wakeword_model_paths=[path])

    def _run(self) -> None:
        import sounddevice as sd
        from jarvis.osctl import MIC_DEVICE

        try:
            oww = self._load_model()
        except Exception as e:
            log.error("Failed to load wake word model: %s", e)
            return

        log.info("Listening for wake word…")
        try:
            with sd.InputStream(
                samplerate=_RATE,
                channels=1,
                dtype="int16",
                blocksize=_CHUNK,
                device=MIC_DEVICE,
            ) as stream:
                while not self._stop_event.is_set():
                    audio, _ = stream.read(_CHUNK)
                    if self.paused:
                        continue
                    preds = oww.predict(audio.flatten())  # expects raw int16 PCM
                    score = max(preds.values()) if preds else 0.0
                    if score >= self._threshold:
                        log.info("Wake word detected (score=%.3f)", score)
                        oww.reset()
                        self._on_wake()
        except Exception as e:
            log.error("Wake word detector error: %s", e)
