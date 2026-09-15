from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum
from ..utils.logger import logger

from ..core.observer import Observer


class UIEventType(str, Enum):
    STATE_CHANGED = "state_changed"
    WAKE_WORD = "wake_word"
    LISTENING = "listening"
    PROCESSING = "processing"
    RESPONDING = "responding"
    SKILL_RESULT = "skill_result"
    DISTANCE_UPDATE = "distance_update"
    GESTURE = "gesture"
    ERROR = "error"


@dataclass
class UIState:
    dialog_state: str = "idle"
    current_skill: Optional[str] = None
    last_text: str = ""
    distance: float = 0.0
    gesture: str = ""
    volume: int = 50
    brightness: int = 80
    is_online: bool = True
    notification: str = ""


class BaseScreen(Observer, ABC):
    def __init__(self, name: str) -> None:
        self._name = name
        self._state = UIState()
        self._enabled = True

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> UIState:
        return self._state

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def update(self, subject, event: str, data: Any = None) -> None:
        if not self._enabled:
            return
        self._handle_event(event, data)

    @abstractmethod
    def _handle_event(self, event: str, data: Any = None) -> None:
        pass

    @abstractmethod
    def render(self) -> None:
        pass

    def update_state(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self._state, key):
                setattr(self._state, key, value)
        if self._enabled:
            self.render()
