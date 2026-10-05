import pytest

from jarvis.brain.router import BrainRouter
from jarvis.core.engine import AgentLoop
from jarvis.core.models import JarvisResponse, ToolCallRequest
from jarvis.tools.registry import ToolRegistry


class FakeProvider:
    """Returns a scripted sequence of responses, one per call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def complete(self, messages, model=None, tools=None):
        self.calls.append((list(messages), model, tools))
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_turn_with_no_tool_calls_returns_text():
    router = BrainRouter(config={})
    fake = FakeProvider([JarvisResponse(text="hello there")])
    loop = AgentLoop(router=router, providers={"groq": fake})

    response = await loop.turn("hi jarvis")

    assert response.text == "hello there"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_turn_executes_tool_call_then_returns_final_text():
    router = BrainRouter(config={})
    registry = ToolRegistry()
    registry.add("get_time", lambda: "10:00", "Get current time")

    fake = FakeProvider(
        [
            JarvisResponse(text="", tool_calls=[ToolCallRequest(id="1", name="get_time", arguments={})]),
            JarvisResponse(text="It's 10:00"),
        ]
    )
    loop = AgentLoop(router=router, registry=registry, providers={"groq": fake})

    response = await loop.turn("what time is it")

    assert response.text == "It's 10:00"
    assert len(fake.calls) == 2
    # tool result should have been appended to history before the 2nd call
    tool_messages = [m for m in loop.history if m.role == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].content == "10:00"


@pytest.mark.asyncio
async def test_turn_routes_code_tasks_to_claude_provider():
    router = BrainRouter(config={})
    fake_groq = FakeProvider([JarvisResponse(text="should not be called")])
    fake_claude = FakeProvider([JarvisResponse(text="refactored!")])
    loop = AgentLoop(router=router, providers={"groq": fake_groq, "claude": fake_claude})

    response = await loop.turn("please refactor this function")

    assert response.text == "refactored!"
    assert len(fake_claude.calls) == 1
    assert len(fake_groq.calls) == 0


@pytest.mark.asyncio
async def test_turn_stops_after_max_iterations():
    router = BrainRouter(config={})
    registry = ToolRegistry()
    registry.add("loop_tool", lambda: "again", "Always calls itself")

    # Every response keeps requesting the same tool call -> should cap out.
    responses = [
        JarvisResponse(text="", tool_calls=[ToolCallRequest(id=str(i), name="loop_tool", arguments={})])
        for i in range(10)
    ]
    fake = FakeProvider(responses)
    loop = AgentLoop(router=router, registry=registry, providers={"groq": fake})

    response = await loop.turn("loop forever")

    assert len(fake.calls) == 5  # MAX_TOOL_ITERATIONS
    assert response.tool_calls  # last response still had a pending tool call
