from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, Optional, Type, TypeVar
from ..utils.logger import logger

T = TypeVar("T")


class Factory(ABC, Generic[T]):
    def __init__(self) -> None:
        self._registry: Dict[str, Type[T]] = {}

    def register(self, key: str, cls: Type[T]) -> None:
        self._registry[key] = cls
        logger.info(f"{self.__class__.__name__} registered: {key} -> {cls.__name__}")

    def unregister(self, key: str) -> None:
        if key in self._registry:
            del self._registry[key]
            logger.info(f"{self.__class__.__name__} unregistered: {key}")

    def create(self, key: str, *args: Any, **kwargs: Any) -> Optional[T]:
        if key not in self._registry:
            logger.warning(f"{self.__class__.__name__}: key not found - {key}")
            return None
        return self._registry[key](*args, **kwargs)

    @property
    def available(self) -> list[str]:
        return list(self._registry.keys())

    def has(self, key: str) -> bool:
        return key in self._registry
