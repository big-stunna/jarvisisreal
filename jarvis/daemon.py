"""
J.A.R.V.I.S. daemon — always-on background process.

Flow:
  boot → idle (silent)
  SIGUSR1 / IPC TOGGLE → enabled ↔ disabled  (sticky)
  enabled + wake word "hey jarvis" → verify speaker → STT → Claude → TTS
  SIGTERM / IPC QUIT → clean shutdown

Toggle is sticky: once disabled, stays off until toggled again.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import threading
from pathlib import Path
from typing import Optional

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
SOCKET_PATH = Path.home() / ".local" / "share" / "jarvis" / "daemon.sock"

log = logging.getLogger("jarvis.daemon")


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler()],
    )


# ── IPC ───────────────────────────────────────────────────────────────────────

class IPCServer:
    """Unix socket IPC. Commands: PING, TOGGLE, QUIT."""

    def __init__(self, loop: asyncio.AbstractEventLoop,
                 shutdown_event: asyncio.Event,
                 toggle_cb):
        self._loop = loop
        self._shutdown_event = shutdown_event
        self._toggle_cb = toggle_cb
        self._server: Optional[socket.socket] = None

    def start(self) -> None:
        SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(SOCKET_PATH))
        self._server.listen(4)
        self._server.settimeout(1.0)
        threading.Thread(target=self._serve, daemon=True, name="jarvis-ipc").start()
        log.info("IPC socket: %s", SOCKET_PATH)

    def stop(self) -> None:
        if self._server:
            try: self._server.close()
            except Exception: pass
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

    def _serve(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                data = conn.recv(64).decode().strip()
                response = self._handle(data)
                conn.sendall((response + "\n").encode())
            finally:
                conn.close()

    def _handle(self, cmd: str) -> str:
        if cmd == "PING":
            return "PONG"
        if cmd == "TOGGLE":
            self._loop.call_soon_threadsafe(self._toggle_cb)
            return "OK"
        if cmd == "QUIT":
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
            return "OK"
        return "UNKNOWN"


def send_ipc(cmd: str) -> str:
    if not SOCKET_PATH.exists():
        return "Daemon not running"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(3.0)
            s.connect(str(SOCKET_PATH))
            s.sendall((cmd + "\n").encode())
            return s.recv(256).decode().strip()
    except Exception as e:
        return f"IPC error: {e}"


# ── voice turn ────────────────────────────────────────────────────────────────

async def _do_voice_turn(agent_loop, hud, model_size: str, tts_voice: str) -> None:
    """Record → verify → transcribe → Claude → speak."""
    import io, wave
    import numpy as np
    from jarvis.voice import stt, tts as tts_mod
    from jarvis.voice.verify import verify

    if hud: hud.listening()

    wav_bytes = stt.record_until_silence()
    if not wav_bytes:
        if hud: hud.idle()
        return

    # Decode WAV bytes → float32 numpy for speaker verification
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        raw = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    wav_f32 = raw.astype(np.float32) / 32768.0

    # Speaker verification
    accepted, score = verify(wav_f32)
    if not accepted:
        log.info("Voice rejected (similarity=%.3f)", score)
        if hud: hud.idle()
        return

    text = stt.transcribe(wav_bytes, model_size=model_size).strip()
    if not text:
        if hud: hud.idle()
        return

    log.info("You: %s", text)
    if hud: hud.thinking(text)

    response = await agent_loop.turn(text)
    reply = response.text.strip()
    log.info("J.A.R.V.I.S.: %s", reply)

    if hud: hud.speaking(reply)
    await tts_mod.speak_async(reply, voice=tts_voice)
    if hud: hud.idle()


# ── main daemon ───────────────────────────────────────────────────────────────

async def run_daemon(no_hud: bool = False, log_level: str = "INFO") -> None:
    _setup_logging(log_level)
    log.info("J.A.R.V.I.S. daemon starting")

    from jarvis.core.config import load_config, load_env
    from jarvis.core.engine import AgentLoop
    from jarvis.tools.registry import ToolRegistry
    from jarvis.tools.system import register_system_tools
    from jarvis.tools.hyprland import register_hyprland_tools
    from jarvis.voice.chimes import play_on, play_off

    load_env()
    config = load_config()

    registry = ToolRegistry()
    register_system_tools(registry)
    register_hyprland_tools(registry)

    agent_loop = AgentLoop(registry=registry)

    audio_cfg  = config.get("audio", {})
    model_size = audio_cfg.get("stt_model", "tiny")
    tts_voice  = audio_cfg.get("tts_voice", "en-GB-RyanNeural")

    # ── HUD ──────────────────────────────────────────────────────────────
    hud = None
    if not no_hud:
        try:
            from jarvis.ui.hud import HUDController, load_theme_colors
            hud = HUDController(colors=load_theme_colors(config))
            log.info("HUD started")
        except Exception as e:
            log.warning("HUD unavailable: %s", e)

    # ── state ─────────────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    enabled = True   # sticky toggle state
    _voice_event = asyncio.Event()

    def _toggle():
        nonlocal enabled
        enabled = not enabled
        if enabled:
            log.info("Jarvis ENABLED")
            play_on()
            if hud: hud.idle()
        else:
            log.info("Jarvis DISABLED")
            play_off()
            if hud: hud.idle()

    def _handle_signal(*_):
        loop.call_soon_threadsafe(shutdown_event.set)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    # SIGUSR1 = toggle
    loop.add_signal_handler(signal.SIGUSR1, _toggle)

    ipc = IPCServer(loop, shutdown_event, _toggle)
    ipc.start()

    # ── wake word ─────────────────────────────────────────────────────────
    def _on_wake():
        if enabled:
            loop.call_soon_threadsafe(_voice_event.set)

    wake = None
    try:
        from jarvis.wake.detector import WakeWordDetector
        wake = WakeWordDetector(on_wake=_on_wake)
        wake.start()
    except Exception as e:
        log.warning("Wake word detector unavailable: %s — using IPC VOICE trigger only", e)

    log.info("Ready. Say 'Hey Jarvis' or send IPC TOGGLE to enable/disable.")

    try:
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(_voice_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            _voice_event.clear()
            if enabled:
                try:
                    await _do_voice_turn(agent_loop, hud, model_size, tts_voice)
                except Exception as e:
                    log.error("Voice turn error: %s", e)
                    if hud: hud.error(str(e))
                    await asyncio.sleep(0.5)
                    if hud: hud.idle()
    finally:
        if wake: wake.stop()
        ipc.stop()
        if hud: hud.stop()
        log.info("Daemon stopped")


def main_daemon(no_hud: bool = False, log_level: str = "INFO") -> None:
    asyncio.run(run_daemon(no_hud=no_hud, log_level=log_level))
