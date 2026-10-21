"""Text-to-speech via edge-tts (online) with paplay playback."""
from __future__ import annotations

import asyncio
import io
import subprocess
import tempfile
import os


async def speak_async(text: str, voice: str = "en-GB-RyanNeural") -> None:
    """Synthesise text and play it through the default audio sink via paplay."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    mp3_buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buf.write(chunk["data"])

    mp3_buf.seek(0)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(mp3_buf.read())
        tmp_path = tmp.name

    try:
        # paplay routes through PipeWire/PulseAudio directly to the active sink
        subprocess.run(["paplay", tmp_path], check=True)
    finally:
        os.unlink(tmp_path)


def speak(text: str, voice: str = "en-GB-RyanNeural") -> None:
    """Blocking wrapper around speak_async."""
    asyncio.run(speak_async(text, voice))
