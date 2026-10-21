import argparse
import asyncio
from rich.console import Console

from jarvis.core.engine import AgentLoop
from jarvis.core.memory import ChatMemory
from jarvis.core.config import load_env
from jarvis.core.models import JarvisResponse
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system import register_system_tools
from jarvis.tools.hyprland import register_hyprland_tools
from jarvis.tools.windows import register_window_tools
from jarvis.tools.files import register_file_tools
from jarvis.tools.everyday import register_everyday_tools
from jarvis.brain.router import BrainRouter
from jarvis.tools.vision import capture_screen, read_clipboard

console = Console(force_terminal=False, highlight=False)


def _say(response: JarvisResponse) -> None:
    console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> {response.text}")
    if response.usage:
        u = response.usage
        console.print(f"[dim]tokens: {u['input']} in / {u['output']} out / {u['thinking']} thinking[/dim]")


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_system_tools(registry)
    register_hyprland_tools(registry)
    register_window_tools(registry)
    register_file_tools(registry)
    register_everyday_tools(registry)
    return registry


async def interactive_chat(offline: bool = False, use_memory: bool = True):
    console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Initializing systems...")

    registry = _build_registry()

    router = BrainRouter(offline=offline)
    memory = ChatMemory() if use_memory else None
    # Load config and build live context if enabled
    from jarvis.core.config import load_config
    config = load_config()
    from jarvis.tools.context import LiveContext
    live_context = LiveContext.from_config(config)
    loop = AgentLoop(router=router, registry=registry, memory=memory, live_context=live_context)
    if memory and memory.count():
        console.print(f"[dim]Memory loaded: {memory.count()} past messages ({memory.db_path}). Type '/forget' to wipe.[/dim]")

    console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Online and listening. (Type 'exit' or 'quit' to stop, '! <cmd>' to run a shell command)")

    while True:
        try:
            user_input = console.input("[bold green]You:[/bold green] ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Shutting down...")
                break
            if user_input == "/forget":
                if memory:
                    memory.clear()
                loop.history = loop.history[:1]
                console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Memory wiped.")
                continue

            # Handle special CLI commands
            if user_input == "/see" or user_input.startswith("/see "):
                query = user_input[4:].strip()
                if not query:
                    console.print("[yellow]Usage: /see <question>[/yellow]")
                    continue
                b64 = capture_screen()
                if not b64:
                    console.print("[yellow]Screenshot capture failed.[/yellow]")
                    continue
                _say(await loop.turn(query, image_b64=b64, image_label="full screen"))
                continue

            if user_input == "/see-region":
                b64 = capture_screen(region=True)
                if not b64:
                    console.print("[yellow]Region capture cancelled or failed.[/yellow]")
                    continue
                query = console.input("[bold green]Question:[/bold green] ").strip() or "What is this?"
                _say(await loop.turn(query, image_b64=b64, image_label="selected region"))
                continue

            if user_input == "/clip" or user_input.startswith("/clip "):
                query = user_input[5:].strip()
                clip = read_clipboard()
                if clip["type"] == "image":
                    _say(await loop.turn(query or "Describe this image.", image_b64=clip["content"], image_label="clipboard image"))
                elif clip["type"] == "text":
                    _say(await loop.turn(f"{query or 'Help me with this:'}\n\n{clip['content']}"))
                else:
                    console.print(f"[yellow]{clip.get('error', 'Clipboard empty')}[/yellow]")
                continue

            _say(await loop.turn(user_input))

        except KeyboardInterrupt:
            console.print("\n[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Shutting down on interrupt...")
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")


async def _voice_or_chat_turn(
    loop, model_size, tts_voice, ducking,
    on_listening, on_thinking, on_speaking, on_idle, hud,
):
    """Race mic recording against stdin. First to arrive wins."""
    import select as _select
    import sys
    import threading
    from jarvis.voice import stt, tts
    from jarvis.voice.duck import ducked

    stop_event = threading.Event()
    wav_result: list = [None]

    def _record():
        from jarvis.voice.duck import ducked
        with ducked(ducking):
            wav_result[0] = stt.record_until_silence(stop_event=stop_event)

    if on_listening:
        on_listening()

    rec_thread = threading.Thread(target=_record, daemon=True)
    rec_thread.start()

    # Poll stdin every 50ms while recording; first keypress wins
    text_input = None
    while rec_thread.is_alive():
        ready, _, _ = _select.select([sys.stdin], [], [], 0.05)
        if ready:
            stop_event.set()
            rec_thread.join(timeout=2.0)
            sys.stdout.write("You: ")
            sys.stdout.flush()
            text_input = sys.stdin.readline().strip()
            break

    if text_input is not None:
        if not text_input:
            if on_idle:
                on_idle()
            return None
        if on_thinking:
            on_thinking(text_input)
    else:
        rec_thread.join()
        wav = wav_result[0]
        if wav is None:
            return None
        text_input = stt.transcribe(wav, model_size=model_size)
        if not text_input:
            if on_idle:
                on_idle()
            return None
        if on_thinking:
            on_thinking(text_input)

    response = await loop.turn(text_input)
    reply = response.text
    if on_speaking:
        on_speaking(reply)
    await tts.speak_async(reply, voice=tts_voice)
    if on_idle:
        on_idle()
    return reply


async def voice_loop(offline: bool = False, use_memory: bool = True, no_hud: bool = False):
    """Continuous voice mode: listen → transcribe → respond → speak."""
    registry = _build_registry()

    router = BrainRouter(offline=offline)
    memory = ChatMemory() if use_memory else None
    from jarvis.core.config import load_config
    config = load_config()
    from jarvis.tools.context import LiveContext
    live_context = LiveContext.from_config(config)
    loop = AgentLoop(router=router, registry=registry, memory=memory, live_context=live_context)

    audio_cfg = config.get("audio", {})
    model_size = audio_cfg.get("stt_model", "base")
    tts_voice = audio_cfg.get("tts_voice", "en-GB-RyanNeural")
    ducking = float(audio_cfg.get("ducking_volume", 0.2))

    from jarvis.voice.pipeline import voice_turn_async

    # ── HUD ──────────────────────────────────────────────────────────────
    hud = None
    if not no_hud:
        try:
            from jarvis.ui.hud import HUDController, load_theme_colors
            hud = HUDController(colors=load_theme_colors(config))
            console.print("[dim]HUD active.[/dim]")
        except Exception as e:
            console.print(f"[dim]HUD unavailable ({e}), continuing without.[/dim]")

    def _on_listening():
        console.print("[dim]  🎙  recording...[/dim]")
        if hud:
            hud.listening()

    def _on_thinking(t: str):
        console.print(f"[bold green]You:[/bold green] {t}")
        if hud:
            hud.thinking(t)

    def _on_speaking(r: str):
        console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> {r}")
        if hud:
            hud.speaking(r)

    def _on_idle():
        if hud:
            hud.idle()

    console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Voice mode active. Speak or type (Ctrl-C to exit).")
    try:
        while True:
            try:
                console.print("[dim]Listening... (or type)[/dim]")
                reply = await _voice_or_chat_turn(
                    loop, model_size, tts_voice, ducking,
                    _on_listening, _on_thinking, _on_speaking, _on_idle, hud,
                )
                if reply is None:
                    console.print("[dim]  (nothing heard)[/dim]")
            except KeyboardInterrupt:
                raise
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")
                if hud:
                    hud.error(str(e))
    except KeyboardInterrupt:
        console.print("\n[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Voice mode off.")
    finally:
        if hud:
            hud.stop()


def main():
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. Digital Assistant")
    parser.add_argument(
        "command", nargs="?", default="chat",
        help="chat | voice | daemon | ipc <CMD> | status",
    )
    parser.add_argument("ipc_cmd", nargs="?", help="IPC command for 'ipc' subcommand")
    parser.add_argument("--offline",   action="store_true", help="Use local Ollama model only")
    parser.add_argument("--no-memory", action="store_true", help="Don't load or save chat history")
    parser.add_argument("--no-hud",    action="store_true", help="Disable the HUD overlay")
    parser.add_argument("--log-level", default="INFO",      help="Logging level for daemon mode")
    args = parser.parse_args()
    load_env()

    if args.command == "chat":
        asyncio.run(interactive_chat(offline=args.offline, use_memory=not args.no_memory))
    elif args.command == "voice":
        asyncio.run(voice_loop(offline=args.offline, use_memory=not args.no_memory, no_hud=args.no_hud))
    elif args.command == "daemon":
        from jarvis.daemon import main_daemon
        main_daemon(offline=args.offline, use_memory=not args.no_memory,
                    no_hud=args.no_hud, log_level=args.log_level)
    elif args.command == "ipc":
        from jarvis.daemon import send_ipc
        cmd = (args.ipc_cmd or "PING").upper()
        console.print(send_ipc(cmd))
    elif args.command == "status":
        from jarvis.daemon import send_ipc
        resp = send_ipc("PING")
        if resp == "PONG":
            console.print("[bold green]Daemon running[/bold green]")
        else:
            console.print(f"[yellow]Daemon not running[/yellow] ({resp})")
    else:
        console.print(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()