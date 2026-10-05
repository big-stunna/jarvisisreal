"""LLM provider clients. Each provider implements the same async interface
so the AgentLoop doesn't need to care which model answered.
"""
import json
import os
from abc import ABC, abstractmethod
from typing import List, Optional

import httpx

from jarvis.core.models import ChatMessage, JarvisResponse, ToolCallRequest


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    async def complete(
        self, messages: List[ChatMessage], model: Optional[str] = None, tools: Optional[list] = None
    ) -> JarvisResponse:
        ...


class GroqProvider(Provider):
    name = "groq"
    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: Optional[str] = None, client: Optional[httpx.AsyncClient] = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.client = client or httpx.AsyncClient(timeout=15.0)

    async def complete(self, messages, model=None, tools=None) -> JarvisResponse:
        payload = {
            "model": model or "llama-3.3-70b-versatile",
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }
        if tools:
            payload["tools"] = tools
        resp = await self.client.post(
            self.BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        return _parse_openai_style(resp.json())


class ClaudeProvider(Provider):
    name = "claude"
    BASE_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: Optional[str] = None, client: Optional[httpx.AsyncClient] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = client or httpx.AsyncClient(timeout=60.0)

    async def complete(self, messages, model=None, tools=None) -> JarvisResponse:
        system = "\n".join(m.content for m in messages if m.role == "system" and isinstance(m.content, str))
        convo = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]
        payload = {
            "model": model or "claude-3-5-sonnet-latest",
            "max_tokens": 4096,
            "messages": convo,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
        resp = await self.client.post(
            self.BASE_URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        text_parts, tool_calls = [], []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCallRequest(id=block["id"], name=block["name"], arguments=block.get("input", {}))
                )
        return JarvisResponse(text="".join(text_parts), tool_calls=tool_calls)


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", client: Optional[httpx.AsyncClient] = None):
        self.base_url = base_url
        self.client = client or httpx.AsyncClient(timeout=60.0)

    async def complete(self, messages, model=None, tools=None) -> JarvisResponse:
        payload = {
            "model": model or "qwen2.5:7b",
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "stream": False,
        }
        resp = await self.client.post(f"{self.base_url}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return JarvisResponse(text=data.get("message", {}).get("content", ""))


def _parse_openai_style(data: dict) -> JarvisResponse:
    choice = data["choices"][0]["message"]
    text = choice.get("content") or ""
    tool_calls = []
    for tc in choice.get("tool_calls") or []:
        tool_calls.append(
            ToolCallRequest(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"].get("arguments") or "{}"),
            )
        )
    return JarvisResponse(text=text, tool_calls=tool_calls)


PROVIDER_REGISTRY = {
    "groq": GroqProvider,
    "claude": ClaudeProvider,
    "ollama": OllamaProvider,
}
