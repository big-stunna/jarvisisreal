"""BrainRouter: decides which LLM provider handles a given task.

Pure routing logic lives here (no network calls) so it's cheap to test.
Actual provider clients live in jarvis/brain/providers.py.
"""
from enum import Enum
from typing import Dict, Optional

from jarvis.core.config import load_config


class TaskType(str, Enum):
    FAST = "fast"        # low-latency conversational / intent parsing -> Gemini
    CODE = "code"         # deep reasoning / multi-file code edits -> Claude
    VISION = "vision"      # screenshot / multimodal queries -> Gemini
    OFFLINE = "offline"     # no network / air-gapped -> Ollama


# Keyword hints used to auto-classify a raw user utterance when the caller
# doesn't already know the task type (e.g. voice pipeline).
_CODE_HINTS = ("code", "refactor", "bug", "function", "class ", "debug", "implement")
_VISION_HINTS = ("screen", "screenshot", "look at", "what's on", "see this", "image")


class BrainRouter:
    def __init__(self, config: Optional[Dict] = None, offline: bool = False):
        self.config = config if config is not None else load_config()
        self.offline = offline
        self.models: Dict[str, str] = (self.config.get("llm", {}) or {}).get("models", {})

    def classify(self, utterance: str) -> TaskType:
        """Best-effort classification of a raw utterance into a TaskType."""
        if self.offline:
            return TaskType.OFFLINE
        lowered = utterance.lower()
        if any(h in lowered for h in _VISION_HINTS):
            return TaskType.VISION
        if any(h in lowered for h in _CODE_HINTS):
            return TaskType.CODE
        return TaskType.FAST

    def route(self, task_type: TaskType) -> str:
        """Map a TaskType -> provider name (groq|claude|gemini|ollama)."""
        if self.offline:
            return "ollama"
        return {
            TaskType.FAST: "gemini",
            TaskType.CODE: "claude",
            TaskType.VISION: "gemini",
            TaskType.OFFLINE: "ollama",
        }[task_type]

    def model_for(self, task_type: TaskType) -> Optional[str]:
        """Resolve the configured model name for a task type, if present."""
        key = {
            TaskType.FAST: "fast",
            TaskType.CODE: "code",
            TaskType.VISION: "vision",
            TaskType.OFFLINE: "offline",
        }[task_type]
        return self.models.get(key)

    def plan(self, utterance: str) -> tuple[TaskType, str, Optional[str]]:
        """Classify once and return (task_type, provider, model)."""
        task_type = self.classify(utterance)
        return task_type, self.route(task_type), self.model_for(task_type)

    def route_utterance(self, utterance: str) -> tuple[str, Optional[str]]:
        _, provider, model = self.plan(utterance)
        return provider, model
