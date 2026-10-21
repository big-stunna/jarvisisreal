"""Microphone capture and transcription via faster-whisper."""
from __future__ import annotations

import io
import queue
import threading
import wave
from typing import Optional

import numpy as np
import sounddevice as sd

_SAMPLE_RATE = 16000
_CHANNELS = 1
_DTYPE = "int16"
_SILENCE_THRESHOLD = 200    # minimum RMS counted as speech; raised to fit room noise
_SILENCE_SECONDS = 1.0      # stop after this many silent seconds
_MAX_SECONDS = 15           # hard cap
_NO_SPEECH_TIMEOUT = 5.0    # bail out if nothing heard within this many seconds


def _rms(chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))


def record_until_silence(
    silence_threshold: int = _SILENCE_THRESHOLD,
    silence_seconds: float = _SILENCE_SECONDS,
    max_seconds: float = _MAX_SECONDS,
    no_speech_timeout: float = _NO_SPEECH_TIMEOUT,
    stop_event: Optional[threading.Event] = None,
) -> bytes:
    """Record from the default mic, stop on silence. Returns WAV bytes."""
    block_size = int(_SAMPLE_RATE * 0.1)  # 100ms chunks
    buf: list[np.ndarray] = []
    q: queue.Queue[np.ndarray] = queue.Queue()
    stop_event = threading.Event()

    def _callback(indata, frames, time, status):  # noqa: ARG001
        q.put(indata.copy())

    with sd.InputStream(
        device="pulse",
        samplerate=_SAMPLE_RATE,
        channels=_CHANNELS,
        dtype=_DTYPE,
        blocksize=block_size,
        callback=_callback,
    ):
        silent_chunks = 0
        silence_limit = int(silence_seconds / 0.1)
        max_chunks = int(max_seconds / 0.1)
        no_speech_limit = int(no_speech_timeout / 0.1)
        total = 0
        started = False
        pre_speech_chunks = 0
        noise: list[float] = []

        while total < max_chunks:
            if stop_event and stop_event.is_set():
                break
            chunk = q.get()
            buf.append(chunk)
            total += 1
            rms = _rms(chunk)
            if total <= 3:
                noise.append(rms)  # first 300 ms: measure room noise floor
                continue
            threshold = max(silence_threshold, min(noise) * 2.2)
            if rms > threshold:
                started = True
                silent_chunks = 0
            elif started:
                silent_chunks += 1
                if silent_chunks >= silence_limit:
                    break
            else:
                pre_speech_chunks += 1
                if pre_speech_chunks >= no_speech_limit:
                    break  # nothing heard, give up early

    raw = np.concatenate(buf, axis=0)
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(2)  # int16 = 2 bytes
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(raw.tobytes())
    return wav_buf.getvalue()


_PROMPT = ("Jarvis, lock the screen. Volume 50. Brightness 30. Mute. "
           "Open Spotify, Discord, Obsidian, Chrome, terminal. Take a screenshot.")
DEFAULT_MODEL = "base.en"


def transcribe(wav_bytes: bytes, model_size: str = DEFAULT_MODEL) -> str:
    """Transcribe WAV bytes with faster-whisper. Returns stripped text."""
    from faster_whisper import WhisperModel  # lazy: heavy import

    model = _get_model(model_size)
    wav_buf = io.BytesIO(wav_bytes)
    segments, _ = model.transcribe(wav_buf, language="en", beam_size=3,
                                   initial_prompt=_PROMPT, vad_filter=True)
    return " ".join(s.text for s in segments).strip()


_model_cache: dict[str, object] = {}


def _get_model(size: str):
    if size not in _model_cache:
        import os
        os.environ.setdefault("HF_HUB_OFFLINE", "1")  # skip network check once cached
        from faster_whisper import WhisperModel
        try:
            _model_cache[size] = WhisperModel(size, device="cpu", compute_type="int8")
        except Exception:
            os.environ["HF_HUB_OFFLINE"] = "0"
            _model_cache[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _model_cache[size]


def listen_and_transcribe(model_size: str = "base") -> Optional[str]:
    """Record until silence, then transcribe. Returns None on empty audio."""
    wav = record_until_silence()
    text = transcribe(wav, model_size=model_size)
    return text or None
