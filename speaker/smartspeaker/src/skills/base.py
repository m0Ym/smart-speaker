from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from ..utils.logger import logger


@dataclass
class SkillResult:
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    speak_text: str = ""


class BaseSkill(ABC):
    def __init__(self, name: str, description: str = "") -> None:
        self._name = name
        self._description = description
        self._enabled = True

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @abstractmethod
    def can_handle(self, intent: str, entities: Dict[str, Any]) -> bool:
        pass

    @abstractmethod
    def execute(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        pass

    def cleanup(self) -> None:
        pass
