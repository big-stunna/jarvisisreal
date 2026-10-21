"""AgentLoop: the core dispatcher that ties BrainRouter + Providers +
ToolRegistry together into a single conversational turn.
"""
from typing import List, Optional, Tuple

from jarvis.brain.providers import PROVIDER_REGISTRY, Provider, provider_available
from jarvis.brain.router import BrainRouter, TaskType
from jarvis.core.memory import ChatMemory
from jarvis.core.models import ChatMessage, JarvisResponse, MessageRole
from jarvis.tools import vision
from jarvis.tools.registry import ToolRegistry

MAX_TOOL_ITERATIONS = 5
VISION_CONTEXT_MESSAGES = 4

# Exception types that indicate a transient network / auth problem worth retrying offline
_NETWORK_ERROR_TYPES = (
    ConnectionError,
    TimeoutError,
    OSError,
)
_NETWORK_ERROR_STRINGS = ("connect", "timeout", "network", "unreachable", "refused", "ssl", "401", "403")


def _is_network_error(exc: Exception) -> bool:
    if isinstance(exc, _NETWORK_ERROR_TYPES):
        return True
    # httpx / aiohttp surface as their own types; check by name + message
    cls = type(exc).__name__.lower()
    msg = str(exc).lower()
    return any(k in cls or k in msg for k in _NETWORK_ERROR_STRINGS)


class AgentLoop:
    def __init__(
        self,
        router: Optional[BrainRouter] = None,
        registry: Optional[ToolRegistry] = None,
        providers: Optional[dict] = None,
        system_prompt: str = "You are J.A.R.V.I.S., a terse and capable Linux desktop assistant.",
        memory: Optional[ChatMemory] = None,
        history_limit: int = 40,
        live_context: Optional["LiveContext"] = None,
    ):
        self.router = router or BrainRouter()
        self.registry = registry or ToolRegistry()
        self.providers: dict = providers or {}
        self.system_prompt = system_prompt
        self.memory = memory
        self.live_context = live_context
        self.history: List[ChatMessage] = [ChatMessage(role=MessageRole.SYSTEM, content=system_prompt)]
        if self.memory:
            self.history.extend(self.memory.recent(history_limit))

    def _append(self, msg: ChatMessage) -> None:
        self.history.append(msg)
        if self.memory:
            self.memory.save(msg)

    @property
    def _config(self) -> dict:
        return getattr(self.router, "config", None) or {}

    @property
    def _models(self) -> dict:
        return (self._config.get("llm", {}) or {}).get("models", {}) or {}

    def _get_provider(self, name: str) -> Provider:
        if name not in self.providers:
            cls = PROVIDER_REGISTRY[name]
            self.providers[name] = cls.from_config(self._config) if hasattr(cls, "from_config") else cls()
        return self.providers[name]

    def _usable(self, name: str) -> bool:
        return name in self.providers or provider_available(name)

    def _vision_target(self) -> Tuple[Optional[str], Optional[str]]:
        if not getattr(self.router, "offline", False) and self._usable("gemini"):
            return "gemini", self._models.get("vision")
        if self._models.get("vision_offline"):
            return "ollama", self._models["vision_offline"]
        return None, None

    async def _vision_turn(self, user_input: str, image_b64: str, label: str) -> JarvisResponse:
        provider_name, model = self._vision_target()
        if provider_name is None:
            response = JarvisResponse(
                text="Vision is unavailable: set GEMINI_API_KEY in .env and run without --offline, "
                "or set llm.models.vision_offline to a local vision model."
            )
        else:
            # Only a few recent text turns go with the image; tools are omitted.
            recent = [
                m for m in self.history[1:]
                if m.role in (MessageRole.USER, MessageRole.ASSISTANT) and isinstance(m.content, str) and m.content
            ][-VISION_CONTEXT_MESSAGES:]
            image_msg = ChatMessage(
                role=MessageRole.USER,
                content=[
                    {"type": "text", "text": user_input},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            )
            response = await self._get_provider(provider_name).complete(
                [self.history[0], *recent, image_msg], model=model, tools=None
            )
        # History keeps a text label, never the image, so later turns don't resend it.
        self._append(ChatMessage(role=MessageRole.USER, content=f"{user_input} [screenshot of: {label}]"))
        self._append(ChatMessage(role=MessageRole.ASSISTANT, content=response.text))
        return response

    async def turn(
        self, user_input: str, image_b64: Optional[str] = None, image_label: str = "image"
    ) -> JarvisResponse:
        """Run one full conversational turn: route -> call LLM -> execute any
        tool calls -> call LLM again -> ... until a text-only response.
        """
        task_type, provider_name, model = self.router.plan(user_input)

        if image_b64 is None and task_type == TaskType.VISION:
            image_b64 = vision.capture_screen(active_window=True) or vision.capture_screen()
            image_label = vision.get_active_window_title() or "screen"
            if image_b64 is None:
                provider_name, model = self.router.route(TaskType.FAST), self.router.model_for(TaskType.FAST)
        if image_b64:
            return await self._vision_turn(user_input, image_b64, image_label)

        if not self._usable(provider_name):
            provider_name, model = "ollama", self._models.get("offline")

        content = user_input
        if self.live_context:
            live_summary = self.live_context.summary()
            if live_summary:
                content += f" [Live context: {live_summary}]"
        self._append(ChatMessage(role=MessageRole.USER, content=content))

        provider = self._get_provider(provider_name)
        response: Optional[JarvisResponse] = None
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await provider.complete(
                self.history, model=model, tools=self.registry.schemas() or None
            )
            self._append(
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
                self._append(
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content=result.content,
                        tool_call_id=result.tool_call_id,
                        name=result.name,
                    )
                )
        return response
