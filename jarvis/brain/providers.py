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
        if not self.api_key:
            return JarvisResponse(text="[color=red]Error: GROQ_API_KEY environment variable is not set.[/color] Please set your API keys or configure J.A.R.V.I.S. in offline mode.")
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
        if not self.api_key:
            return JarvisResponse(text="[color=red]Error: ANTHROPIC_API_KEY environment variable is not set.[/color] Please set your API keys or configure J.A.R.V.I.S. in offline mode.")

        system_parts = []
        for m in messages:
            if m.role.value == "system":
                if isinstance(m.content, str):
                    system_parts.append(m.content)
                elif isinstance(m.content, list):
                    system_parts.extend([b.get("text", "") for b in m.content if b.get("type") == "text"])
        system = "\n".join(system_parts)

        convo = []
        for m in messages:
            if m.role.value == "system":
                continue

            content = m.content
            if isinstance(content, list):
                # Convert OpenAI-style image_url blocks to Anthropic format
                anthropic_content = []
                for block in content:
                    if block.get("type") == "text":
                        anthropic_content.append({"type": "text", "text": block.get("text", "")})
                    elif block.get("type") == "image_url":
                        url = block.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            mime_type = url[5:url.find(";")]
                            base64_data = url.split("base64,")[1]
                            anthropic_content.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": base64_data,
                                },
                            })
                content = anthropic_content

            convo.append({"role": m.role.value, "content": content})

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
        self.client = client or httpx.AsyncClient(timeout=120.0)  # vision models are slower

    async def complete(self, messages, model=None, tools=None) -> JarvisResponse:
        ollama_messages = []
        for m in messages:
            msg = {"role": m.role.value}

            if isinstance(m.content, list):
                text_parts = []
                images = []
                for block in m.content:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "image_url":
                        # Ollama wants raw base64, not a data URI
                        url = block.get("image_url", {}).get("url", "")
                        if "base64," in url:
                            images.append(url.split("base64,")[1])
                        else:
                            images.append(url)
                msg["content"] = "\n".join(text_parts)
                if images:
                    msg["images"] = images
            else:
                msg["content"] = m.content or ""

            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.name:
                msg["name"] = m.name

            ollama_messages.append(msg)

        payload = {
            "model": model or "qwen2.5:7b",
            "messages": ollama_messages,
            "stream": False,
            # Evict vision model after 5 min idle so it doesn't hog VRAM in online mode
            "keep_alive": "5m",
        }
        if tools:
            payload["tools"] = tools

        try:
            resp = await self.client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
        except httpx.RequestError:
            return JarvisResponse(text="[color=red]Error: Could not connect to local Ollama instance.[/color] Make sure Ollama is running and accessible at " + self.base_url)

        data = resp.json()
        choice = data.get("message", {})

        tool_calls = []
        for tc in choice.get("tool_calls", []):
            tool_calls.append(
                ToolCallRequest(
                    id=tc.get("id") or "call_0",
                    name=tc["function"]["name"],
                    arguments=tc["function"].get("arguments", {}),
                )
            )

        return JarvisResponse(text=choice.get("content", ""), tool_calls=tool_calls)


class GeminiProvider(Provider):
    name = "gemini"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    def __init__(self, api_key: Optional[str] = None, client: Optional[httpx.AsyncClient] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.client = client or httpx.AsyncClient(timeout=60.0)

    def _format_messages(self, messages: List[ChatMessage]) -> list:
        """Serialize ChatMessages to OpenAI-compatible dicts; image_url blocks pass through as-is."""
        result = []
        for m in messages:
            if isinstance(m.content, list):
                result.append({"role": m.role.value, "content": m.content})
            else:
                result.append({"role": m.role.value, "content": m.content})
        return result

    async def complete(self, messages, model=None, tools=None) -> JarvisResponse:
        if not self.api_key:
            return JarvisResponse(text="[color=red]Error: GEMINI_API_KEY environment variable is not set.[/color] Please set your API keys or configure J.A.R.V.I.S. in offline mode.")
        payload = {
            "model": model or "gemini-1.5-flash",
            "messages": self._format_messages(messages),
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
    "gemini": GeminiProvider,
}
