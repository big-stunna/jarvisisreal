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
        threshold: float = 0.5,
        model_name: str = _MODEL,
    ):
        self._on_wake = on_wake
        self._threshold = threshold
        self._model_name = model_name
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._oww = None

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
        from openwakeword.model import Model
        return Model(wakeword_models=[self._model_name], inference_framework="onnx")

    def _run(self) -> None:
        import sounddevice as sd

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
                device="pulse",
            ) as stream:
                while not self._stop_event.is_set():
                    audio, _ = stream.read(_CHUNK)
                    audio_f32 = audio.flatten().astype(np.float32) / 32768.0
                    oww.predict(audio_f32)
                    scores = oww.prediction_buffer.get(self._model_name, [])
                    if scores and scores[-1] >= self._threshold:
                        log.info("Wake word detected (score=%.3f)", scores[-1])
                        oww.reset()
                        self._on_wake()
        except Exception as e:
            log.error("Wake word detector error: %s", e)
