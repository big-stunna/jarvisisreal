"""BrainRouter: always routes to claude-cli."""
from __future__ import annotations

from enum import Enum
from typing import Dict, Optional

from jarvis.core.config import load_config


class TaskType(str, Enum):
    FAST = "fast"


class BrainRouter:
    def __init__(self, config: Optional[Dict] = None, offline: bool = False):
        self.config = config if config is not None else load_config()
        self.offline = offline

    def plan(self, utterance: str) -> tuple[TaskType, str, Optional[str]]:
        return TaskType.FAST, "claude-cli", None

    def route(self, task_type: TaskType) -> str:
        return "claude-cli"

    def model_for(self, task_type: TaskType) -> Optional[str]:
        return None

    def route_utterance(self, utterance: str) -> tuple[str, Optional[str]]:
        return "claude-cli", None

    def classify(self, utterance: str) -> TaskType:
        return TaskType.FAST
