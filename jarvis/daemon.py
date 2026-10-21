"""
Jarvis daemon entry point.

Runs the voice loop as a proper background service:
- Logs via Python logging (captured by systemd journal via stderr)
- Handles SIGTERM / SIGINT for graceful shutdown
- Exposes a Unix socket for IPC (trigger a voice turn, show/hide HUD)
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
        handlers=[logging.StreamHandler()],  # systemd captures stderr
    )


# ── IPC socket ────────────────────────────────────────────────────────────────

class IPCServer:
    """
    Tiny Unix-domain socket server.
    Commands (newline-terminated strings):
      PING           → PONG
      VOICE          → trigger one voice turn
      HIDE           → hide HUD
      SHOW           → show HUD
      QUIT           → graceful shutdown
    """
    def __init__(self, loop: asyncio.AbstractEventLoop, shutdown_event: asyncio.Event):
        self._loop = loop
        self._shutdown_event = shutdown_event
        self._voice_trigger: Optional[asyncio.Event] = None
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def set_voice_trigger(self, event: asyncio.Event) -> None:
        self._voice_trigger = event

    def start(self) -> None:
        SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(SOCKET_PATH))
        self._server.listen(4)
        self._server.settimeout(1.0)
        self._thread = threading.Thread(target=self._serve, daemon=True, name="jarvis-ipc")
        self._thread.start()
        log.info("IPC socket: %s", SOCKET_PATH)

    def stop(self) -> None:
        if self._server:
            self._server.close()
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
        if cmd == "VOICE" and self._voice_trigger:
            self._loop.call_soon_threadsafe(self._voice_trigger.set)
            return "OK"
        if cmd == "QUIT":
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
            return "OK"
        return "UNKNOWN"


def send_ipc(cmd: str) -> str:
    """Send a command to a running daemon. Returns the response or an error."""
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


# ── main daemon loop ──────────────────────────────────────────────────────────

async def run_daemon(
    offline: bool = False,
    use_memory: bool = True,
    no_hud: bool = False,
    log_level: str = "INFO",
) -> None:
    _setup_logging(log_level)
    log.info("J.A.R.V.I.S. daemon starting (offline=%s)", offline)

    from jarvis.core.config import load_config, load_env
    from jarvis.core.engine import AgentLoop
    from jarvis.core.memory import ChatMemory
    from jarvis.brain.router import BrainRouter
    from jarvis.tools.registry import ToolRegistry
    from jarvis.tools.system import register_system_tools
    from jarvis.tools.hyprland import register_hyprland_tools
    from jarvis.tools.windows import register_window_tools
    from jarvis.tools.files import register_file_tools
    from jarvis.tools.everyday import register_everyday_tools
    from jarvis.tools.context import LiveContext
    from jarvis.voice.pipeline import voice_turn_async

    load_env()
    config = load_config()

    registry = ToolRegistry()
    register_system_tools(registry)
    register_hyprland_tools(registry)
    register_window_tools(registry)
    register_file_tools(registry)
    register_everyday_tools(registry)

    router = BrainRouter(offline=offline)
    memory = ChatMemory() if use_memory else None
    live_context = LiveContext.from_config(config)
    agent_loop = AgentLoop(router=router, registry=registry, memory=memory, live_context=live_context)

    audio_cfg = config.get("audio", {})
    model_size   = audio_cfg.get("stt_model", "base")
    tts_voice    = audio_cfg.get("tts_voice", "en-GB-RyanNeural")
    ducking      = float(audio_cfg.get("ducking_volume", 0.2))

    # ── HUD ──────────────────────────────────────────────────────────────
    hud = None
    if not no_hud:
        try:
            from jarvis.ui.hud import HUDController, load_theme_colors
            hud = HUDController(colors=load_theme_colors(config))
            log.info("HUD started")
        except Exception as e:
            log.warning("HUD unavailable: %s", e)

    # ── shutdown / IPC ────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _handle_signal(*_):
        log.info("Signal received, shutting down")
        loop.call_soon_threadsafe(shutdown_event.set)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    ipc = IPCServer(loop, shutdown_event)
    ipc.start()

    # ── voice loop ────────────────────────────────────────────────────────
    log.info("Voice loop running. Send SIGTERM or IPC QUIT to stop.")

    def _on_listening():
        log.debug("Listening...")
        if hud: hud.listening()

    def _on_thinking(t: str):
        log.info("You: %s", t)
        if hud: hud.thinking(t)

    def _on_speaking(r: str):
        log.info("J.A.R.V.I.S.: %s", r)
        if hud: hud.speaking(r)

    def _on_idle():
        if hud: hud.idle()

    try:
        while not shutdown_event.is_set():
            try:
                await voice_turn_async(
                    agent_loop,
                    model_size=model_size,
                    tts_voice=tts_voice,
                    ducking_volume=ducking,
                    on_listening=_on_listening,
                    on_thinking=_on_thinking,
                    on_speaking=_on_speaking,
                    on_idle=_on_idle,
                )
            except Exception as e:
                log.error("Voice turn error: %s", e)
                await asyncio.sleep(1)
    finally:
        ipc.stop()
        if hud:
            hud.stop()
        log.info("Daemon stopped")


def main_daemon(offline: bool = False, use_memory: bool = True,
                no_hud: bool = False, log_level: str = "INFO") -> None:
    asyncio.run(run_daemon(offline=offline, use_memory=use_memory,
                           no_hud=no_hud, log_level=log_level))
