"""AgentLoop: routes each turn through ClaudeCliProvider + ToolRegistry."""
from __future__ import annotations

from typing import List, Optional

from jarvis.brain.providers import GroqThenClaude
from jarvis.core.memory import ChatMemory
from jarvis.core.models import ChatMessage, JarvisResponse, MessageRole
from jarvis.tools.registry import ToolRegistry

MAX_TOOL_ITERATIONS = 5


class AgentLoop:
    def __init__(
        self,
        router=None,          # kept for API compat, unused
        registry: Optional[ToolRegistry] = None,
        providers: Optional[dict] = None,
        system_prompt: str = "",
        memory: Optional[ChatMemory] = None,
        history_limit: int = 20,
        live_context=None,    # kept for API compat, unused
    ):
        self.registry = registry or ToolRegistry()
        from jarvis.core.config import load_env
        load_env()
        self._provider = GroqThenClaude()
        self.system_prompt = system_prompt
        self.memory = memory
        self.history: List[ChatMessage] = [
            ChatMessage(role=MessageRole.SYSTEM, content=system_prompt)
        ]
        if self.memory:
            self.history.extend(self.memory.recent(history_limit))

    def _append(self, msg: ChatMessage) -> None:
        self.history.append(msg)
        if self.memory:
            self.memory.save(msg)

    async def turn(self, user_input: str, image_b64=None, image_label: str = "image") -> JarvisResponse:
        # Try fast command dispatch first (brightness, volume, open apps, etc.)
        from jarvis.tools.dispatcher import dispatch as _dispatch
        cmd_result = await _dispatch(user_input)
        if cmd_result is not None:
            self._append(ChatMessage(role=MessageRole.USER, content=user_input))
            self._append(ChatMessage(role=MessageRole.ASSISTANT, content=cmd_result))
            return JarvisResponse(text=cmd_result)

        self._append(ChatMessage(role=MessageRole.USER, content=user_input))

        response: Optional[JarvisResponse] = None
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await self._provider.complete(
                self.history,
                tools=self.registry.schemas() or None,
            )
            self._append(ChatMessage(
                role=MessageRole.ASSISTANT,
                content=response.text,
                tool_calls=[tc.model_dump() for tc in response.tool_calls] or None,
            ))
            if not response.tool_calls:
                break
            for call in response.tool_calls:
                result = await self.registry.execute(call)
                self._append(ChatMessage(
                    role=MessageRole.TOOL,
                    content=result.content,
                    tool_call_id=result.tool_call_id,
                    name=result.name,
                ))

        return response
