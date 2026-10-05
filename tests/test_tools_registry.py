import pytest

from jarvis.core.models import ToolCallRequest
from jarvis.tools.registry import ToolRegistry


def test_register_and_schema():
    registry = ToolRegistry()

    @registry.register("add", "Add two numbers", {"type": "object", "properties": {"a": {}, "b": {}}})
    def add(a: int, b: int) -> int:
        return a + b

    schemas = registry.schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "add"


@pytest.mark.asyncio
async def test_execute_sync_tool():
    registry = ToolRegistry()
    registry.add("add", lambda a, b: a + b, "Add two numbers")
    call = ToolCallRequest(id="1", name="add", arguments={"a": 2, "b": 3})
    result = await registry.execute(call)
    assert result.content == "5"
    assert result.error is False


@pytest.mark.asyncio
async def test_execute_async_tool():
    registry = ToolRegistry()

    async def greet(name: str) -> str:
        return f"hello {name}"

    registry.add("greet", greet, "Greet someone")
    call = ToolCallRequest(id="2", name="greet", arguments={"name": "jarvis"})
    result = await registry.execute(call)
    assert result.content == "hello jarvis"


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error():
    registry = ToolRegistry()
    call = ToolCallRequest(id="3", name="nope", arguments={})
    result = await registry.execute(call)
    assert result.error is True
    assert "Unknown tool" in result.content


@pytest.mark.asyncio
async def test_execute_tool_that_raises_returns_error_result():
    registry = ToolRegistry()

    def boom():
        raise ValueError("kaboom")

    registry.add("boom", boom, "Explode")
    call = ToolCallRequest(id="4", name="boom", arguments={})
    result = await registry.execute(call)
    assert result.error is True
    assert "kaboom" in result.content
