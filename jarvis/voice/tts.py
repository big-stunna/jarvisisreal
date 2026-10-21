"""Text-to-speech via edge-tts (online) with sounddevice playback."""
from __future__ import annotations

import asyncio
import io
import tempfile
import os


async def speak_async(text: str, voice: str = "en-GB-RyanNeural") -> None:
    """Synthesise text and play it through the default audio sink."""
    import edge_tts
    import sounddevice as sd
    import soundfile as sf

    communicate = edge_tts.Communicate(text, voice)
    mp3_buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buf.write(chunk["data"])

    mp3_buf.seek(0)
    # edge-tts returns MP3; write to a temp file so soundfile can decode via libsndfile/ffmpeg
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(mp3_buf.read())
        tmp_path = tmp.name

    try:
        data, samplerate = sf.read(tmp_path, dtype="float32")
        sd.play(data, samplerate, device="pulse")
        sd.wait()
    finally:
        os.unlink(tmp_path)


def speak(text: str, voice: str = "en-GB-RyanNeural") -> None:
    """Blocking wrapper around speak_async."""
    asyncio.run(speak_async(text, voice))
