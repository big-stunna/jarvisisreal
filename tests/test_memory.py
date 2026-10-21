import pytest

from jarvis.core.engine import AgentLoop
from jarvis.core.memory import ChatMemory
from jarvis.core.models import ChatMessage, JarvisResponse, MessageRole


class FakeProvider:
    async def complete(self, messages, model=None, tools=None):
        return JarvisResponse(text=f"seen {len(messages)}")


class FakeRouter:
    def plan(self, text):
        from jarvis.brain.router import TaskType
        return TaskType.FAST, "fake", None


def test_save_and_recent_roundtrip(tmp_path):
    mem = ChatMemory(tmp_path / "m.db")
    mem.save(ChatMessage(role=MessageRole.SYSTEM, content="sys"))
    mem.save(ChatMessage(role=MessageRole.USER, content="hi"))
    mem.save(ChatMessage(role=MessageRole.TOOL, content="x", tool_call_id="1", name="t"))
    mem.save(ChatMessage(role=MessageRole.ASSISTANT, content="hello"))
    assert [m.content for m in ChatMemory(tmp_path / "m.db").recent()] == ["hi", "hello"]


def test_recent_limit_and_clear(tmp_path):
    mem = ChatMemory(tmp_path / "m.db")
    for i in range(5):
        mem.save(ChatMessage(role=MessageRole.USER, content=str(i)))
    assert [m.content for m in mem.recent(2)] == ["3", "4"]
    mem.clear()
    assert mem.count() == 0


async def test_agent_loop_persists_across_instances(tmp_path):
    db = tmp_path / "m.db"
    loop1 = AgentLoop(router=FakeRouter(), providers={"fake": FakeProvider()}, memory=ChatMemory(db))
    await loop1.turn("remember 42")
    loop2 = AgentLoop(router=FakeRouter(), providers={"fake": FakeProvider()}, memory=ChatMemory(db))
    assert [m.content for m in loop2.history[1:]] == ["remember 42", "seen 2"]
