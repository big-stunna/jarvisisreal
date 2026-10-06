"""ChatMemory: SQLite-backed persistent chat history so J.A.R.V.I.S.
remembers past conversations across restarts.
"""
import json
import os
import sqlite3
from pathlib import Path
from typing import List, Optional

from jarvis.core.models import ChatMessage, MessageRole

DEFAULT_DB_PATH = Path(
    os.environ.get("JARVIS_DATA_DIR", Path.home() / ".local" / "share" / "jarvis")
) / "memory.db"


class ChatMemory:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_call_id TEXT,
                name TEXT,
                tool_calls TEXT
            )"""
        )
        self.conn.commit()

    def save(self, msg: ChatMessage) -> None:
        if msg.role == MessageRole.SYSTEM:
            return  # system prompt is rebuilt on each start
        self.conn.execute(
            "INSERT INTO messages (role, content, tool_call_id, name, tool_calls) VALUES (?, ?, ?, ?, ?)",
            (
                msg.role.value,
                json.dumps(msg.content),
                msg.tool_call_id,
                msg.name,
                json.dumps(msg.tool_calls) if msg.tool_calls else None,
            ),
        )
        self.conn.commit()

    def recent(self, limit: int = 40) -> List[ChatMessage]:
        """Return the last `limit` user/assistant messages, oldest first.

        Tool messages are skipped so a truncated window never starts with an
        orphaned tool result (providers reject that).
        """
        rows = self.conn.execute(
            "SELECT role, content FROM messages WHERE role IN ('user', 'assistant') "
            "AND content != '\"\"' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [ChatMessage(role=MessageRole(r), content=json.loads(c)) for r, c in reversed(rows)]

    def clear(self) -> None:
        self.conn.execute("DELETE FROM messages")
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
