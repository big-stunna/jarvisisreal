"""Vision turns: image sent once, minimal context, no tools, never stored."""
import json
from unittest.mock import patch

import httpx
import pytest

from jarvis.brain.providers import GeminiProvider
from jarvis.brain.router import BrainRouter
from jarvis.core.config import load_env
from jarvis.core.engine import VISION_CONTEXT_MESSAGES, AgentLoop
from jarvis.core.memory import ChatMemory
from jarvis.core.models import ChatMessage, JarvisResponse, MessageRole
from jarvis.tools.registry import ToolRegistry


class FakeProvider:
    def __init__(self, text="ok"):
        self.text = text
        self.calls = []

    async def complete(self, messages, model=None, tools=None):
        self.calls.append((list(messages), model, tools))
        return JarvisResponse(text=self.text)


def _loop(providers, memory=None, offline=False, models=None):
    router = BrainRouter(config={"llm": {"models": models or {}}}, offline=offline)
    registry = ToolRegistry()
    registry.add("get_time", lambda: "10:00", "Get current time")
    return AgentLoop(router=router, registry=registry, providers=providers, memory=memory)


async def test_explicit_image_goes_to_gemini_once_without_tools():
    gemini = FakeProvider()
    loop = _loop({"gemini": gemini})
    await loop.turn("what is this error", image_b64="AAAA", image_label="full screen")

    assert len(gemini.calls) == 1
    messages, _, tools = gemini.calls[0]
    assert tools is None
    user_msgs = [m for m in messages if m.role == MessageRole.USER]
    assert len(user_msgs) == 1, "question must not be sent twice"
    assert isinstance(user_msgs[0].content, list)


async def test_image_not_kept_in_history_or_memory(tmp_path):
    gemini = FakeProvider()
    loop = _loop({"gemini": gemini}, memory=ChatMemory(tmp_path / "m.db"))
    await loop.turn("read this", image_b64="SECRETB64", image_label="clipboard image")

    assert all("SECRETB64" not in str(m.content) for m in loop.history)
    reloaded = _loop({"gemini": gemini}, memory=ChatMemory(tmp_path / "m.db"))
    assert [m.content for m in reloaded.history[1:]] == ["read this [screenshot of: clipboard image]", "ok"]


async def test_vision_context_is_trimmed():
    gemini = FakeProvider()
    loop = _loop({"gemini": gemini})
    for i in range(10):
        loop.history.append(ChatMessage(role=MessageRole.USER, content=f"old {i}"))
    await loop.turn("look", image_b64="AAAA")

    messages, _, _ = gemini.calls[0]
    assert len(messages) == 1 + VISION_CONTEXT_MESSAGES + 1  # system + recent + image


async def test_offline_without_local_vision_model_explains_instead_of_calling():
    ollama = FakeProvider()
    loop = _loop({"ollama": ollama, "gemini": FakeProvider()}, offline=True)
    response = await loop.turn("what is this", image_b64="AAAA")
    assert "Vision is unavailable" in response.text
    assert ollama.calls == []


async def test_offline_uses_local_vision_model_when_configured():
    ollama = FakeProvider()
    loop = _loop({"ollama": ollama}, offline=True, models={"vision_offline": "gemma3:4b"})
    await loop.turn("what is this", image_b64="AAAA")
    assert ollama.calls[0][1] == "gemma3:4b"


async def test_auto_vision_capture_failure_falls_back_to_text(monkeypatch):
    nvidia_fast = FakeProvider("text answer")
    loop = _loop({"nvidia": nvidia_fast, "gemini": FakeProvider()})
    with patch("jarvis.core.engine.vision.capture_screen", return_value=None), \
         patch("jarvis.core.engine.vision.get_active_window_title", return_value=None):
        response = await loop.turn("what's on my screen")
    assert response.text == "text answer"


async def test_missing_key_falls_back_to_ollama(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    ollama = FakeProvider("local")
    loop = _loop({"ollama": ollama}, models={"offline": "qwen2.5:7b"})
    response = await loop.turn("hello")
    assert response.text == "local"
    assert ollama.calls[0][1] == "qwen2.5:7b"


# --- GeminiProvider (native API) ---

def _gemini(handler, **kw):
    return GeminiProvider(api_key="k", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


OK_BODY = {
    "candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": "It's a TypeError."}]}}],
    "usageMetadata": {"promptTokenCount": 270, "candidatesTokenCount": 6},
}


async def test_gemini_payload_uses_low_token_settings():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="sys"),
        ChatMessage(role=MessageRole.ASSISTANT, content="earlier"),
        ChatMessage(role=MessageRole.USER, content=[
            {"type": "text", "text": "what"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
        ]),
    ]
    resp = await _gemini(handler).complete(msgs, model="gemini-3.5-flash", tools=[{"x": 1}])

    body = seen["body"]
    assert "gemini-3.5-flash:generateContent" in seen["url"]
    assert body["generationConfig"]["mediaResolution"] == "MEDIA_RESOLUTION_LOW"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert body["generationConfig"]["maxOutputTokens"] == 1024
    assert "tools" not in body
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert [c["role"] for c in body["contents"]] == ["model", "user"]
    assert body["contents"][1]["parts"][1] == {"inline_data": {"mime_type": "image/jpeg", "data": "QUJD"}}
    assert resp.text == "It's a TypeError."
    assert resp.usage == {"input": 270, "output": 6, "thinking": 0}


async def test_gemini_retries_fallback_model_when_busy():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if "primary" in str(request.url):
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return httpx.Response(200, json=OK_BODY)

    resp = await _gemini(handler, fallback_model="backup").complete(
        [ChatMessage(role=MessageRole.USER, content="hi")], model="primary"
    )
    assert len(urls) == 2 and "backup" in urls[1]
    assert resp.text == "It's a TypeError."


async def test_gemini_error_is_returned_not_raised():
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "bad key"}})

    resp = await _gemini(handler).complete([ChatMessage(role=MessageRole.USER, content="hi")])
    assert resp.text == "Gemini error 400: bad key"


def test_gemini_from_config_reads_settings():
    p = GeminiProvider.from_config({
        "gemini": {"media_resolution": "medium", "thinking_level": "low", "max_output_tokens": 256},
        "llm": {"models": {"vision_fallback": "gemini-3.8-flash"}},
    })
    assert (p.media_resolution, p.thinking_level, p.max_output_tokens, p.fallback_model) == (
        "medium", "low", 256, "gemini-3.8-flash"
    )


def test_load_env_sets_missing_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nA_KEY=fromfile\nB_KEY=\nC_KEY=\"quoted\"\n")
    monkeypatch.setenv("A_KEY", "real")
    monkeypatch.delenv("B_KEY", raising=False)
    monkeypatch.delenv("C_KEY", raising=False)
    load_env(env)
    import os
    assert os.environ["A_KEY"] == "real"
    assert "B_KEY" not in os.environ
    assert os.environ["C_KEY"] == "quoted"
