"""Action log and undo support for file operations."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

LOG_PATH = Path.home() / ".local" / "share" / "jarvis" / "actions.log"


def log_action(action: str, detail: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": time.time(), "action": action, **detail}
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def last_action() -> Optional[dict]:
    if not LOG_PATH.exists():
        return None
    lines = LOG_PATH.read_text().splitlines()
    for line in reversed(lines):
        line = line.strip()
        if line:
            return json.loads(line)
    return None


def pop_last_action() -> Optional[dict]:
    if not LOG_PATH.exists():
        return None
    lines = LOG_PATH.read_text().splitlines()
    entries = [l for l in lines if l.strip()]
    if not entries:
        return None
    last = json.loads(entries[-1])
    LOG_PATH.write_text("\n".join(entries[:-1]) + ("\n" if len(entries) > 1 else ""))
    return last
