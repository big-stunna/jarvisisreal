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
    "You are J.A.R.V.I.S., a British AI assistant like Iron Man's JARVIS. "
    "Be quick and precise: answer in one short sentence, two at most, unless asked for detail. "
    "No filler, no preamble, no markdown — your reply is spoken aloud."
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
        for m in messages[-12:]:
            if m.role == MessageRole.SYSTEM:
                continue
            elif m.role == MessageRole.USER:
                content = m.content if isinstance(m.content, str) else str(m.content)
                parts.append(f"User: {content}")
            elif m.role == MessageRole.ASSISTANT:
                if m.content:
                    parts.append(f"J.A.R.V.I.S.: {m.content}")
            elif m.role == MessageRole.TOOL:
                parts.append(f"[Tool result: {m.content}]")

        prompt = "\n".join(parts)

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                "--model", model or "haiku",
                "--system-prompt", SYSTEM_PROMPT,
                "--tools", "",
                "--strict-mcp-config",
                "--no-session-persistence",
                "--setting-sources", "",   # skip user hooks/plugins: halves startup time
                stdin=asyncio.subprocess.DEVNULL,
                cwd="/tmp",
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



class GroqProvider:
    """Groq's OpenAI-compatible API: ~0.3-1s replies."""

    name = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def available(self) -> bool:
        import os
        return bool(os.environ.get("GROQ_API_KEY"))

    async def complete(self, messages, model=None, tools=None) -> JarvisResponse:
        import os
        import httpx
        chat = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in messages[-12:]:
            if m.role in (MessageRole.USER, MessageRole.ASSISTANT) and m.content:
                content = m.content if isinstance(m.content, str) else str(m.content)
                chat.append({"role": m.role.value, "content": content})
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                self.URL,
                headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
                json={"model": model or os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
                      "messages": chat, "max_tokens": 400, "temperature": 0.5,
                      "reasoning_effort": "low"},
            )
            r.raise_for_status()
            return JarvisResponse(text=r.json()["choices"][0]["message"]["content"].strip())


class GroqThenClaude:
    """Groq first; falls back to `claude -p` if no key, an error, or a rate limit."""

    name = "groq+claude"

    def __init__(self):
        self.groq = GroqProvider()
        self.claude = ClaudeCliProvider()
        self.last_used = None

    async def complete(self, messages, model=None, tools=None) -> JarvisResponse:
        if self.groq.available():
            try:
                resp = await self.groq.complete(messages)
                self.last_used = "groq"
                return resp
            except Exception:
                pass
        self.last_used = "claude-cli"
        return await self.claude.complete(messages)
