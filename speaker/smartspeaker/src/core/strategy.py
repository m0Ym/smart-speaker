from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar
from ..utils.logger import logger


class Strategy(ABC):
    @abstractmethod
    def execute(self, *args: Any, **kwargs: Any) -> Any:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    def cleanup(self) -> None:
        pass


class StrategyManager:
    def __init__(self) -> None:
        self._strategies: Dict[str, Strategy] = {}
        self._current_strategy: Optional[str] = None

    def register(self, strategy: Strategy) -> None:
        self._strategies[strategy.name] = strategy
        logger.info(f"Strategy registered: {strategy.name}")

    def unregister(self, name: str) -> None:
        if name in self._strategies:
            self._strategies[name].cleanup()
            del self._strategies[name]
            logger.info(f"Strategy unregistered: {name}")

    def set_current(self, name: str) -> bool:
        if name not in self._strategies:
            logger.warning(f"Strategy not found: {name}")
            return False
        self._current_strategy = name
        logger.info(f"Strategy switched to: {name}")
        return True

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        if not self._current_strategy:
            raise ValueError("No strategy set")
        return self._strategies[self._current_strategy].execute(*args, **kwargs)

    @property
    def current(self) -> Optional[str]:
        return self._current_strategy

    @property
    def available(self) -> List[str]:
        return list(self._strategies.keys())
