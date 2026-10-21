"""Voice pipeline: mic → STT → AgentLoop → TTS, with audio ducking."""
from __future__ import annotations

import asyncio
from typing import Optional

from jarvis.voice.duck import ducked


async def voice_turn_async(
    agent_loop,
    model_size: str = "base",
    tts_voice: str = "en-GB-RyanNeural",
    ducking_volume: float = 0.2,
    on_listening: Optional[callable] = None,
    on_thinking: Optional[callable] = None,
    on_speaking: Optional[callable] = None,
    on_idle: Optional[callable] = None,
) -> Optional[str]:
    """
    One full voice turn: record → transcribe → turn() → speak.
    Returns the assistant's text response, or None if nothing was heard.
    Callbacks let the HUD hook in; on_idle fires after speaking finishes.
    """
    from jarvis.voice import stt, tts

    if on_listening:
        on_listening()

    with ducked(ducking_volume):
        wav = stt.record_until_silence()

    text = stt.transcribe(wav, model_size=model_size)
    if not text:
        if on_idle:
            on_idle()
        return None

    if on_thinking:
        on_thinking(text)

    response = await agent_loop.turn(text)
    reply = response.text

    if on_speaking:
        on_speaking(reply)

    with ducked(ducking_volume):
        await tts.speak_async(reply, voice=tts_voice)

    if on_idle:
        on_idle()

    return reply


def voice_turn(
    agent_loop,
    model_size: str = "base",
    tts_voice: str = "en-GB-RyanNeural",
    ducking_volume: float = 0.2,
    on_listening=None,
    on_thinking=None,
    on_speaking=None,
) -> Optional[str]:
    """Blocking wrapper for voice_turn_async."""
    return asyncio.run(
        voice_turn_async(
            agent_loop,
            model_size=model_size,
            tts_voice=tts_voice,
            ducking_volume=ducking_volume,
            on_listening=on_listening,
            on_thinking=on_thinking,
            on_speaking=on_speaking,
        )
    )
