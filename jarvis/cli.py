import argparse
import asyncio
from rich.console import Console

from jarvis.core.engine import AgentLoop
from jarvis.core.memory import ChatMemory
from jarvis.core.models import ChatMessage, MessageRole
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system import register_system_tools
from jarvis.tools.hyprland import register_hyprland_tools
from jarvis.brain.router import BrainRouter

console = Console()


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
            if user_input.startswith("/see "):
                # /see <query> - capture full screen and send query
                from jarvis.tools.vision import capture_screen
                query = user_input[5:].strip()
                if not query:
                    console.print("[yellow]Usage: /see <query>[/yellow]")
                    continue
                b64 = capture_screen()
                if b64:
                    content = [
                        {"type": "text", "text": query},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ]
                    memory_text = f"{query} [screenshot of: full screen]"
                    loop._append(ChatMessage(role=MessageRole.USER, content=content), memory_text=memory_text)
                    response = await loop.turn(query)
                    console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> {response.text}")
                else:
                    console.print("[yellow]Screenshot capture failed.[/yellow]")
                continue

            if user_input == "/see-region":
                # /see-region - interactive region selection capture
                from jarvis.tools.vision import capture_screen
                b64 = capture_screen(region=True)
                if b64:
                    query = console.input("[bold green]Query:[/bold green] ").strip()
                    if query:
                        content = [
                            {"type": "text", "text": query},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ]
                        memory_text = f"{query} [screenshot of: selected region]"
                        loop._append(ChatMessage(role=MessageRole.USER, content=content), memory_text=memory_text)
                        response = await loop.turn(query)
                        console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> {response.text}")
                else:
                    console.print("[yellow]Region capture cancelled or failed.[/yellow]")
                continue

            if user_input == "/clip":
                # /clip - paste clipboard and query
                from jarvis.tools.vision import read_clipboard
                clip = read_clipboard()
                if clip["type"] == "image":
                    content = [
                        {"type": "text", "text": "Analyze this clipboard image:"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{clip['content']}"}},
                    ]
                    memory_text = "[Analyze clipboard image]"
                    loop._append(ChatMessage(role=MessageRole.USER, content=content), memory_text=memory_text)
                    response = await loop.turn("Analyze this clipboard image:")
                    console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> {response.text}")
                elif clip["type"] == "text":
                    preview = clip['content'][:200] + "..." if len(clip['content']) > 200 else clip['content']
                    console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Clipboard text: {preview}")
                else:
                    console.print(f"[yellow]{clip.get('error', 'Clipboard empty')}[/yellow]")
                continue

            response = await loop.turn(user_input)
            console.print(f"[bold cyan]J.A.R.V.I.S.[/bold cyan] >> {response.text}")

        except KeyboardInterrupt:
            console.print("\n[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Shutting down on interrupt...")
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")


def main():
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. Digital Assistant")
    parser.add_argument("command", nargs="?", default="chat", help="Command to run (chat, enroll-voice)")
    parser.add_argument("--offline", action="store_true", help="Run entirely using local Ollama model")
    parser.add_argument("--no-memory", action="store_true", help="Don't load or save chat history")
    args = parser.parse_args()

    if args.command == "chat":
        asyncio.run(interactive_chat(offline=args.offline, use_memory=not args.no_memory))
    else:
        console.print(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()