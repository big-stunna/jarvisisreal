"""J.A.R.V.I.S. CLI entry point."""
from __future__ import annotations

import argparse
import asyncio
from rich.console import Console

from jarvis.core.config import load_env
from jarvis.core.engine import AgentLoop
from jarvis.core.models import JarvisResponse
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system import register_system_tools
from jarvis.tools.hyprland import register_hyprland_tools

console = Console(force_terminal=False, highlight=False)


def _say(response: JarvisResponse) -> None:
    console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> {response.text}")


def _build_loop() -> AgentLoop:
    registry = ToolRegistry()
    register_system_tools(registry)
    register_hyprland_tools(registry)
    return AgentLoop(registry=registry)


# ── chat ──────────────────────────────────────────────────────────────────────

async def interactive_chat():
    loop = _build_loop()
    console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Online. Type 'exit' to quit.")
    while True:
        try:
            user_input = console.input("[bold green]You:[/bold green] ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                break
            _say(await loop.turn(user_input))
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")


# ── voice mode ────────────────────────────────────────────────────────────────

async def voice_loop(no_hud: bool = False):
    """Continuous voice: listen → transcribe → Claude CLI → TTS."""
    import select as _select
    import sys, termios, tty, threading
    from jarvis.voice import stt, tts
    from jarvis.core.config import load_config

    loop = _build_loop()
    cfg = load_config().get("audio", {})
    model_size = cfg.get("stt_model", "tiny")
    tts_voice  = cfg.get("tts_voice", "en-GB-RyanNeural")

    hud = None
    if not no_hud:
        try:
            from jarvis.ui.hud import HUDController
            hud = HUDController()
        except Exception as e:
            console.print(f"[dim]HUD unavailable: {e}[/dim]")

    def _start_rec():
        stop_ev = threading.Event()
        result  = [None]
        def _rec(): result[0] = stt.record_until_silence()
        t = threading.Thread(target=_rec, daemon=True)
        t.start()
        return stop_ev, result, t

    console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Voice mode. Speak or type (Ctrl-C to exit).")
    next_rec = None
    try:
        while True:
            stop_ev, result, rec_t = next_rec or _start_rec()
            if hud: hud.listening()

            # Race: mic vs keypress
            text_input = None
            old = termios.tcgetattr(sys.stdin.fileno())
            try:
                tty.setcbreak(sys.stdin.fileno())
                while rec_t.is_alive():
                    rdy, _, _ = _select.select([sys.stdin], [], [], 0.05)
                    if rdy:
                        ch = sys.stdin.read(1)
                        stop_ev.set()
                        rec_t.join(timeout=2.0)
                        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)
                        sys.stdout.write(f"\nYou: {ch}")
                        sys.stdout.flush()
                        rest = sys.stdin.readline()
                        text_input = (ch + rest).strip()
                        break
            finally:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)

            if text_input is None:
                rec_t.join()
                wav = result[0]
                if not wav:
                    next_rec = None
                    continue
                text_input = stt.transcribe(wav, model_size=model_size).strip()

            if not text_input:
                next_rec = None
                continue

            console.print(f"[bold green]You:[/bold green] {text_input}")
            if hud: hud.thinking(text_input)

            response = await loop.turn(text_input)
            reply = response.text
            console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> {reply}")
            if hud: hud.speaking(reply)

            # Start next recording BEFORE TTS plays
            next_rec = _start_rec()

            await tts.speak_async(reply, voice=tts_voice)
            if hud: hud.idle()

    except KeyboardInterrupt:
        console.print("\n[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Voice mode off.")
    finally:
        if hud: hud.stop()


# ── enroll ────────────────────────────────────────────────────────────────────

async def enroll_voice():
    """Record 10 seconds of the user's voice and save a voiceprint."""
    from jarvis.voice.stt import record_until_silence
    from jarvis.voice.verify import enroll
    import io, wave
    import numpy as np

    console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Speak for ~10 seconds to enroll your voice.")
    console.print("[dim]Recording... (speak naturally)[/dim]")

    # Record up to 10s
    wav_bytes = record_until_silence(max_seconds=10.0, no_speech_timeout=12.0)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        raw = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    wav_f32 = raw.astype(np.float32) / 32768.0

    enroll(wav_f32)
    console.print("[bold green]Voiceprint saved.[/bold green] Only your voice will activate J.A.R.V.I.S.")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S.")
    parser.add_argument(
        "command", nargs="?", default="chat",
        help="chat | voice | start | stop | toggle | status | enroll",
    )
    parser.add_argument("--no-hud",    action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    load_env()

    if args.command == "chat":
        asyncio.run(interactive_chat())

    elif args.command == "voice":
        asyncio.run(voice_loop(no_hud=args.no_hud))

    elif args.command in ("start", "daemon"):
        from jarvis.daemon import main_daemon
        main_daemon(no_hud=args.no_hud, log_level=args.log_level)

    elif args.command == "stop":
        from jarvis.daemon import send_ipc
        console.print(send_ipc("QUIT"))

    elif args.command == "toggle":
        from jarvis.daemon import send_ipc
        console.print(send_ipc("TOGGLE"))

    elif args.command == "status":
        from jarvis.daemon import send_ipc
        resp = send_ipc("PING")
        if resp == "PONG":
            console.print("[bold green]Daemon running[/bold green]")
        else:
            console.print(f"[yellow]Daemon not running[/yellow]")

    elif args.command == "enroll":
        asyncio.run(enroll_voice())

    elif args.command == "gui":
        from jarvis.ui.chat_window import launch
        launch()

    else:
        console.print(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
