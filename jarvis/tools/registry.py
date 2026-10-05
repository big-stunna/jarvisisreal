"""Tool registry: maps tool names -> callables, with JSON-schema-ish
parameter metadata so providers that support function calling can be fed
a tool spec, and the AgentLoop can dispatch ToolCallRequests.
"""
import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from jarvis.core.models import ToolCallRequest, ToolResult


@dataclass
class Tool:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters or {"type": "object", "properties": {}},
        }


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, name: str, description: str = "", parameters: Optional[Dict] = None):
        """Decorator: @registry.register("name", "desc") on a function."""

        def decorator(func: Callable) -> Callable:
            self._tools[name] = Tool(name=name, description=description, func=func, parameters=parameters or {})
            return func

        return decorator

    def add(self, name: str, func: Callable, description: str = "", parameters: Optional[Dict] = None) -> None:
        self._tools[name] = Tool(name=name, description=description, func=func, parameters=parameters or {})

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def schemas(self) -> List[Dict[str, Any]]:
        return [t.to_schema() for t in self._tools.values()]

    async def execute(self, call: ToolCallRequest) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=call.id, name=call.name, content=f"Unknown tool: {call.name}", error=True
            )
        try:
            if inspect.iscoroutinefunction(tool.func):
                result = await tool.func(**call.arguments)
            else:
                result = await asyncio.to_thread(tool.func, **call.arguments)
            return ToolResult(tool_call_id=call.id, name=call.name, content=str(result), error=False)
        except Exception as exc:  # noqa: BLE001 - surfaced to the LLM, not swallowed
            return ToolResult(tool_call_id=call.id, name=call.name, content=f"Error: {exc}", error=True)
