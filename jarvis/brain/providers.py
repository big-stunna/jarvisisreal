"""
Brain providers — single ClaudeCliProvider that shells out to `claude -p`.
All other providers (Gemini, NVIDIA, OpenRouter, Groq, Ollama) removed.
"""
from __future__ import annotations

import asyncio
import shutil
from typing import List, Optional

from jarvis.core.models import ChatMessage, JarvisResponse, MessageRole


SYSTEM_PROMPT = (
    "You are J.A.R.V.I.S., a terse and capable AI assistant with a British accent. "
    "You speak like the Iron Man J.A.R.V.I.S. — confident, dry wit, extremely concise. "
    "Never say you're an AI. Answer in 1-3 sentences unless more is genuinely needed."
)


class ClaudeCliProvider:
    """Calls `claude -p <prompt>` as a subprocess. Uses the user's Claude.ai session."""

    name = "claude-cli"

    async def complete(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        tools=None,
    ) -> JarvisResponse:
        if not shutil.which("claude"):
            return JarvisResponse(text="Error: `claude` CLI not found in PATH.")

        # Build prompt: system + conversation history collapsed into one string
        parts: list[str] = []
        system_injected = False
        for m in messages:
            if m.role == MessageRole.SYSTEM:
                parts.append(f"[System: {m.content}]")
                system_injected = True
            elif m.role == MessageRole.USER:
                content = m.content if isinstance(m.content, str) else str(m.content)
                parts.append(f"User: {content}")
            elif m.role == MessageRole.ASSISTANT:
                if m.content:
                    parts.append(f"J.A.R.V.I.S.: {m.content}")
            elif m.role == MessageRole.TOOL:
                parts.append(f"[Tool result: {m.content}]")

        if not system_injected:
            parts.insert(0, f"[System: {SYSTEM_PROMPT}]")

        prompt = "\n".join(parts)

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            text = stdout.decode().strip()
            if not text and stderr:
                text = f"Error: {stderr.decode().strip()}"
            return JarvisResponse(text=text or "…")
        except asyncio.TimeoutError:
            return JarvisResponse(text="Request timed out.")
        except Exception as e:
            return JarvisResponse(text=f"Claude CLI error: {e}")


# Registry shim — engine.py uses PROVIDER_REGISTRY and provider_available
PROVIDER_REGISTRY: dict = {"claude-cli": ClaudeCliProvider}


def provider_available(name: str) -> bool:
    if name == "claude-cli":
        return bool(shutil.which("claude"))
    return False
