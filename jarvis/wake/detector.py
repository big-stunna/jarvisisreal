"""
Wake word detector using openWakeWord.
Listens on the mic continuously at low sample rate.
Calls on_wake() when "hey jarvis" (or configured word) is detected.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("jarvis.wake")

_CHUNK = 1280        # 80 ms at 16kHz — required by openWakeWord
_RATE  = 16000
_MODEL = "hey_jarvis"   # bundled openWakeWord model


_NAME_RE = re.compile(r"\b(jarvis|jarvas|jervis|javis|jarviz|jarvi|charvis|garvis|service jarvis)\b")


class _SpeechKeywordSpotter:
    """Second-stage wake detector: transcribes short speech bursts with Whisper
    tiny and fires if they contain "Jarvis". Catches accents openWakeWord misses."""

    _FRAME = 1280 / _RATE           # seconds per chunk (80 ms)
    _END_SILENCE = 5                # chunks of quiet that end a burst (~0.4 s)
    _MIN_LEN, _MAX_LEN = 3, 50      # burst length in chunks (0.25 s .. 4 s)

    def __init__(self, on_hit: Callable[[str], None]):
        self._on_hit = on_hit
        self._floor = None
        self._burst: list[np.ndarray] = []
        self._quiet = 0
        self._busy = threading.Event()
        self._model = None
        self.ready = False
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            from jarvis.voice.stt import _get_model
            self._model = _get_model("tiny")
        except Exception as e:
            log.warning("Keyword spotter unavailable: %s", e)
        finally:
            self.ready = True

    def reset(self):
        self._burst, self._quiet = [], 0

    def feed(self, chunk: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        if self._floor is None:
            self._floor = rms
        speaking = rms > max(250.0, self._floor * 1.6)
        if not speaking and not self._burst:
            self._floor = 0.95 * self._floor + 0.05 * rms  # track room noise
        if speaking:
            self._burst.append(chunk)
            self._quiet = 0
        elif self._burst:
            self._burst.append(chunk)
            self._quiet += 1
            if self._quiet >= self._END_SILENCE:
                self._finish()
        if len(self._burst) > self._MAX_LEN:
            self.reset()  # long speech (music, conversation): not a wake phrase

    def _finish(self):
        burst, self._burst, self._quiet = self._burst, [], 0
        if len(burst) - self._END_SILENCE < self._MIN_LEN or self._model is None or self._busy.is_set():
            return
        self._busy.set()
        threading.Thread(target=self._check, args=(np.concatenate(burst),), daemon=True).start()

    def _check(self, audio: np.ndarray):
        try:
            # No initial_prompt: Whisper echoes the prompt on unclear audio (false wakes).
            segs, _ = self._model.transcribe(
                audio.astype(np.float32) / 32768.0, language="en", beam_size=1,
                condition_on_previous_text=False, temperature=0.0)
            segs = [g for g in segs if g.no_speech_prob < 0.5 and g.avg_logprob > -0.8]
            text = " ".join(g.text for g in segs).lower().strip()
            if text and len(text.split()) <= 5 and _NAME_RE.search(text):
                self._on_hit(text)
        except Exception as e:
            log.debug("Keyword spotter error: %s", e)
        finally:
            self._busy.clear()


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
        from jarvis.osctl import MIC_DEVICE, bt_headset_connected

        try:
            oww = self._load_model()
        except Exception as e:
            log.error("Failed to load wake word model: %s", e)
            return

        last_fire = [0.0]

        def fire(source: str):
            if self.paused or time.monotonic() - last_fire[0] < 2.0:
                return
            last_fire[0] = time.monotonic()
            log.info("Wake word detected (%s)", source)
            oww.reset(); kws.reset()
            self._on_wake()

        kws = _SpeechKeywordSpotter(lambda text: fire(f"heard {text!r}"))

        backed_off = False
        while not self._stop_event.is_set():
            if bt_headset_connected():
                if not backed_off:
                    log.info("Bluetooth headset connected; wake word off (use SUPER+SHIFT+V)")
                    backed_off = True
                self._stop_event.wait(5.0)
                continue
            backed_off = False
            self._listen(sd, MIC_DEVICE, oww, kws, fire)
            if not self._stop_event.is_set():
                time.sleep(1.0)
                sd._terminate(); sd._initialize()  # refresh devices after suspend/hotplug

    def _listen(self, sd, device, oww, kws, fire) -> None:
        """Run one mic stream until it stalls, the system resumes from sleep, or stop()."""
        import queue
        q: queue.Queue = queue.Queue(maxsize=200)

        def callback(indata, frames, t, status):
            try:
                q.put_nowait(indata.copy())
            except queue.Full:
                pass

        from jarvis.osctl import bt_headset_connected
        next_bt_check = time.monotonic() + 5.0

        def suspend_gap() -> float:  # BOOTTIME keeps counting during sleep, MONOTONIC doesn't
            return time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()

        gap = suspend_gap() if hasattr(time, "CLOCK_BOOTTIME") else 0.0
        log.info("Listening for wake word…")
        try:
            with sd.InputStream(samplerate=_RATE, channels=1, dtype="int16",
                                blocksize=_CHUNK, device=device, callback=callback):
                while not self._stop_event.is_set():
                    try:
                        audio = q.get(timeout=3.0)
                    except queue.Empty:
                        log.warning("Mic stream stalled; reopening")
                        return
                    if hasattr(time, "CLOCK_BOOTTIME") and suspend_gap() - gap > 2.0:
                        log.info("Resumed from sleep; reopening mic")
                        return
                    if time.monotonic() >= next_bt_check:
                        next_bt_check = time.monotonic() + 5.0
                        if bt_headset_connected():
                            return
                    if self.paused:
                        kws.reset()
                        continue
                    chunk = audio.flatten()
                    preds = oww.predict(chunk)  # expects raw int16 PCM
                    score = max(preds.values()) if preds else 0.0
                    if score >= self._threshold:
                        fire(f"score={score:.3f}")
                    else:
                        kws.feed(chunk)
        except Exception as e:
            log.error("Mic stream error: %s; reopening", e)
