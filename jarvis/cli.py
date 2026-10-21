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
from jarvis.brain.router import BrainRouter
from jarvis.tools.vision import capture_screen, read_clipboard

console = Console()


def _say(response: JarvisResponse) -> None:
    console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> {response.text}")
    if response.usage:
        u = response.usage
        console.print(f"[dim]tokens: {u['input']} in / {u['output']} out / {u['thinking']} thinking[/dim]")


async def interactive_chat(offline: bool = False, use_memory: bool = True):
    console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Initializing systems...")

    registry = ToolRegistry()
    register_system_tools(registry)
    register_hyprland_tools(registry)

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


async def voice_loop(offline: bool = False, use_memory: bool = True):
    """Continuous voice mode: listen → transcribe → respond → speak."""
    registry = ToolRegistry()
    register_system_tools(registry)
    register_hyprland_tools(registry)

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

    console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Voice mode active. Speak now (Ctrl-C to exit).")
    while True:
        try:
            console.print("[dim]Listening...[/dim]")
            reply = await voice_turn_async(
                loop,
                model_size=model_size,
                tts_voice=tts_voice,
                ducking_volume=ducking,
                on_listening=lambda: console.print("[dim]  🎙  recording...[/dim]"),
                on_thinking=lambda t: console.print(f"[bold green]You:[/bold green] {t}"),
                on_speaking=lambda r: console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> {r}"),
            )
            if reply is None:
                console.print("[dim]  (nothing heard)[/dim]")
        except KeyboardInterrupt:
            console.print("\n[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Voice mode off.")
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")


def main():
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. Digital Assistant")
    parser.add_argument("command", nargs="?", default="chat", help="Command to run (chat, voice, enroll-voice)")
    parser.add_argument("--offline", action="store_true", help="Run entirely using local Ollama model")
    parser.add_argument("--no-memory", action="store_true", help="Don't load or save chat history")
    args = parser.parse_args()
    load_env()

    if args.command == "chat":
        asyncio.run(interactive_chat(offline=args.offline, use_memory=not args.no_memory))
    elif args.command == "voice":
        asyncio.run(voice_loop(offline=args.offline, use_memory=not args.no_memory))
    else:
        console.print(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()