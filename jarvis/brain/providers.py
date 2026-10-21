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


class NvidiaProvider(Provider):
    """NVIDIA Build OpenAI-compatible endpoint — 1000 free req/model/month."""
    name = "nvidia"
    BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

    def __init__(self, api_key: Optional[str] = None, client: Optional[httpx.AsyncClient] = None):
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", "")
        self.client = client or httpx.AsyncClient(timeout=30.0)

    async def complete(self, messages, model=None, tools=None) -> JarvisResponse:
        if not self.api_key:
            return JarvisResponse(text="Error: NVIDIA_API_KEY not set in .env.")
        payload = {
            "model": model or "meta/llama-3.3-70b-instruct",
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
    """Native generateContent API: the OpenAI-compatible endpoint can't set
    mediaResolution or thinkingLevel, which are the main token levers
    (measured: LOW image = 264 tokens vs 1100 default; minimal thinking = 0)."""

    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    RETRYABLE = {429, 500, 503}

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        media_resolution: str = "low",
        thinking_level: str = "minimal",
        max_output_tokens: int = 1024,
        fallback_model: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.client = client or httpx.AsyncClient(timeout=60.0)
        self.media_resolution = media_resolution
        self.thinking_level = thinking_level
        self.max_output_tokens = max_output_tokens
        self.fallback_model = fallback_model

    @classmethod
    def from_config(cls, config: dict) -> "GeminiProvider":
        g = config.get("gemini", {}) or {}
        return cls(
            media_resolution=g.get("media_resolution", "low"),
            thinking_level=g.get("thinking_level", "minimal"),
            max_output_tokens=int(g.get("max_output_tokens", 1024)),
            fallback_model=((config.get("llm", {}) or {}).get("models", {}) or {}).get("vision_fallback"),
        )

    @staticmethod
    def _parts(content) -> list:
        if isinstance(content, str):
            return [{"text": content}] if content else []
        parts = []
        for block in content or []:
            if block.get("type") == "text" and block.get("text"):
                parts.append({"text": block["text"]})
            elif block.get("type") == "image_url":
                url = block.get("image_url", {}).get("url", "")
                if url.startswith("data:") and "base64," in url:
                    parts.append({"inline_data": {"mime_type": url[5:url.find(";")], "data": url.split("base64,", 1)[1]}})
        return parts

    def _payload(self, messages: List[ChatMessage]) -> dict:
        system, contents = [], []
        for m in messages:
            role = m.role.value
            if role == "system":
                system.extend(self._parts(m.content))
                continue
            if role == "tool":
                # Gemini wants functionResponse inside a user turn
                contents.append({"role": "user", "parts": [{"functionResponse": {
                    "name": m.name or "tool",
                    "response": {"result": m.content or ""},
                }}]})
                continue
            parts = self._parts(m.content)
            # Also emit any assistant tool_calls as functionCall parts (with thought_signature if present)
            if role == "assistant" and m.tool_calls:
                for tc in m.tool_calls:
                    fc = {"name": tc["name"], "args": tc.get("arguments", {})}
                    if tc.get("thought_signature"):
                        fc["thoughtSignature"] = tc["thought_signature"]
                    parts.append({"functionCall": fc})
            if parts:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": self.max_output_tokens,
                "mediaResolution": f"MEDIA_RESOLUTION_{self.media_resolution.upper()}",
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": system}
        return payload

    @staticmethod
    def _openai_tools_to_gemini(tools: list) -> list:
        """Convert tool schemas to Gemini functionDeclarations.
        Handles both flat {name, description, parameters} and OpenAI {type, function: {...}}."""
        decls = []
        for t in tools or []:
            # flat format used by ToolRegistry
            if "name" in t:
                fn = t
            else:
                fn = t.get("function", {})
            decl = {"name": fn.get("name", ""), "description": fn.get("description", "")}
            if fn.get("parameters"):
                decl["parameters"] = fn["parameters"]
            decls.append(decl)
        return [{"functionDeclarations": decls}] if decls else []

    async def complete(self, messages, model=None, tools=None) -> JarvisResponse:
        if not self.api_key:
            return JarvisResponse(text="Error: GEMINI_API_KEY is not set in .env.")
        payload = self._payload(messages)
        # Don't send tools on vision turns — images + tool schemas waste tokens
        has_image = any(
            isinstance(m.content, list) and any(b.get("type") == "image_url" for b in m.content)
            for m in messages
        )
        if tools and not has_image:
            payload["tools"] = self._openai_tools_to_gemini(tools)
        models = [model or "gemini-3.5-flash"]
        if self.fallback_model and self.fallback_model not in models:
            models.append(self.fallback_model)

        resp = None
        for m in models:
            resp = await self.client.post(
                self.URL.format(model=m), headers={"x-goog-api-key": self.api_key}, json=payload
            )
            if resp.status_code not in self.RETRYABLE:
                break
        if resp.status_code != 200:
            try:
                msg = resp.json().get("error", {}).get("message", "")
            except ValueError:
                msg = resp.text[:200]
            # Raise on transient errors so engine.py can fall back to Ollama
            if resp.status_code in self.RETRYABLE:
                raise ConnectionError(f"Gemini error {resp.status_code}: {msg}")
            return JarvisResponse(text=f"Gemini error {resp.status_code}: {msg}")

        data = resp.json()
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought") and "functionCall" not in p)
        tool_calls = []
        for i, p in enumerate(parts):
            fc = p.get("functionCall")
            if fc:
                tool_calls.append(ToolCallRequest(
                    id=f"call_{i}",
                    name=fc.get("name", ""),
                    arguments=fc.get("args", {}),
                    thought_signature=fc.get("thoughtSignature"),
                ))
        u = data.get("usageMetadata", {})
        usage = {
            "input": u.get("promptTokenCount", 0),
            "output": u.get("candidatesTokenCount", 0),
            "thinking": u.get("thoughtsTokenCount", 0),
        }
        return JarvisResponse(text=text, tool_calls=tool_calls, usage=usage)


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


PROVIDER_KEY_ENV = {
    "groq": "GROQ_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
}


def provider_available(name: str) -> bool:
    env = PROVIDER_KEY_ENV.get(name)
    return env is None or bool(os.environ.get(env))


PROVIDER_REGISTRY = {
    "groq": GroqProvider,
    "claude": ClaudeProvider,
    "ollama": OllamaProvider,
    "gemini": GeminiProvider,
    "nvidia": NvidiaProvider,
}
