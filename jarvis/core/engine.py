"""AgentLoop: the core dispatcher that ties BrainRouter + Providers +
ToolRegistry together into a single conversational turn.
"""
from typing import List, Optional, Tuple

from jarvis.brain.providers import PROVIDER_REGISTRY, Provider
from jarvis.brain.router import BrainRouter, TaskType
from jarvis.core.memory import ChatMemory
from jarvis.core.models import ChatMessage, JarvisResponse, MessageRole
from jarvis.tools.registry import ToolRegistry

# Import vision lazily — won't fail if grim/slurp aren't installed yet
try:
    from jarvis.tools.vision import capture_screen, get_active_window_geometry
    _VISION_AVAILABLE = True
except ImportError:
    _VISION_AVAILABLE = False

MAX_TOOL_ITERATIONS = 5


def _sanitise_for_memory(content) -> str:
    """Return a safe string to store in SQLite — strips base64 image blobs."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image_url":
                    parts.append("[image]")
            else:
                parts.append(str(block))
        return " ".join(p for p in parts if p)
    return str(content) if content else ""


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

    def _append(self, msg: ChatMessage, *, memory_text: Optional[str] = None) -> None:
        """Append msg to in-memory history and persist to SQLite.

        ``memory_text`` overrides what is written to SQLite when the real
        content contains binary data (e.g. base64 image blobs) that should
        never be stored verbatim.
        """
        self.history.append(msg)
        if self.memory:
            if memory_text is not None:
                # Write a sanitised copy so base64 never hits the DB
                from jarvis.core.models import ChatMessage as _CM
                sanitised = _CM(
                    role=msg.role,
                    content=memory_text,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                    tool_calls=msg.tool_calls,
                )
                self.memory.save(sanitised)
            else:
                self.memory.save(msg)

    def _get_provider(self, name: str) -> Provider:
        if name not in self.providers:
            provider_cls = PROVIDER_REGISTRY[name]
            self.providers[name] = provider_cls()
        return self.providers[name]

    def _build_vision_message(self, user_input: str) -> tuple[ChatMessage, str]:
        """Build a multimodal user message with an active-window screenshot.

        Returns (message, memory_text) where memory_text is the sanitised
        string to store in SQLite instead of the raw image content.
        """
        # Capture the active window; fall back to full screen if geometry fails
        b64 = None
        window_title = "active window"
        if _VISION_AVAILABLE:
            geometry_str = get_active_window_geometry()
            if geometry_str:
                # Try to pull the window title for the memory label
                try:
                    import json, subprocess
                    raw = subprocess.run(
                        ["hyprctl", "activewindow", "-j"],
                        capture_output=True, text=True, check=True
                    )
                    data = json.loads(raw.stdout)
                    window_title = data.get("title") or data.get("class") or "active window"
                except Exception:
                    pass
            b64 = capture_screen(active_window=True)
            if b64 is None:
                b64 = capture_screen()  # full screen fallback

        if b64:
            content = [
                {"type": "text", "text": user_input},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                },
            ]
            memory_text = f"{user_input} [screenshot of: {window_title}]"
        else:
            # Vision unavailable or capture failed — send text only
            content = user_input
            memory_text = user_input

        return (
            ChatMessage(role=MessageRole.USER, content=content),
            memory_text,
        )

    async def turn(self, user_input: str) -> JarvisResponse:
        """Run one full conversational turn: route -> call LLM -> execute any
        tool calls -> call LLM again -> ... until a text-only response.
        """
        provider_name, model = self.router.route_utterance(user_input)
        task_type = self.router.classify(user_input)

        # Auto-attach screenshot for VISION queries; optionally inject live context
        extra_context = ""
        if self.live_context:
            live_summary = self.live_context.summary()
            if live_summary:
                extra_context = f" [Live context: {live_summary}]"

        if task_type == TaskType.VISION and _VISION_AVAILABLE:
            user_msg, memory_text = self._build_vision_message(user_input)
            # Append live context to user input for vision analysis
            if extra_context:
                memory_text += extra_context
                if isinstance(user_msg.content, list):
                    # Add text block with extra context
                    user_msg.content.insert(0, {"type": "text", "text": user_input + extra_context})
                else:
                    user_msg.content = user_input + extra_context
            self._append(user_msg, memory_text=memory_text)
        else:
            content = user_input
            if extra_context:
                content += extra_context
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
