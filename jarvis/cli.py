import argparse
from rich.console import Console

console = Console()

def main():
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. Digital Assistant")
    parser.add_argument("command", nargs="?", default="chat", help="Command to run (chat, enroll-voice)")
    args = parser.parse_args()

    if args.command == "chat":
        console.print("[bold cyan]J.A.R.V.I.S.[/bold cyan] >> Online and listening...")
    else:
        console.print(f"Unknown command: {args.command}")

if __name__ == "__main__":
    main()
