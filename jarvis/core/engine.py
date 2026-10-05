"""AgentLoop: the core dispatcher that ties BrainRouter + Providers +
ToolRegistry together into a single conversational turn.
"""
from typing import List, Optional

from jarvis.brain.providers import PROVIDER_REGISTRY, Provider
from jarvis.brain.router import BrainRouter
from jarvis.core.models import ChatMessage, JarvisResponse, MessageRole
from jarvis.tools.registry import ToolRegistry

MAX_TOOL_ITERATIONS = 5


class AgentLoop:
    def __init__(
        self,
        router: Optional[BrainRouter] = None,
        registry: Optional[ToolRegistry] = None,
        providers: Optional[dict] = None,
        system_prompt: str = "You are J.A.R.V.I.S., a terse and capable Linux desktop assistant.",
    ):
        self.router = router or BrainRouter()
        self.registry = registry or ToolRegistry()
        self.providers: dict = providers or {}
        self.system_prompt = system_prompt
        self.history: List[ChatMessage] = [ChatMessage(role=MessageRole.SYSTEM, content=system_prompt)]

    def _get_provider(self, name: str) -> Provider:
        if name not in self.providers:
            provider_cls = PROVIDER_REGISTRY[name]
            self.providers[name] = provider_cls()
        return self.providers[name]

    async def turn(self, user_input: str) -> JarvisResponse:
        """Run one full conversational turn: route -> call LLM -> execute any
        tool calls -> call LLM again -> ... until a text-only response.
        """
        self.history.append(ChatMessage(role=MessageRole.USER, content=user_input))

        provider_name, model = self.router.route_utterance(user_input)
        provider = self._get_provider(provider_name)

        response: Optional[JarvisResponse] = None
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await provider.complete(
                self.history, model=model, tools=self.registry.schemas() or None
            )
            self.history.append(
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=response.text,
                    tool_calls=[tc.model_dump() for tc in response.tool_calls] or None,
                )
            )
            if not response.tool_calls:
                break
            for call in response.tool_calls:
                result = await self.registry.execute(call)
                self.history.append(
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content=result.content,
                        tool_call_id=result.tool_call_id,
                        name=result.name,
                    )
                )
        return response
