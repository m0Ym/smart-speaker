from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
from ..utils.logger import logger


class Observer(ABC):
    @abstractmethod
    def update(self, subject: "Subject", event: str, data: Any = None) -> None:
        pass


class Subject:
    def __init__(self) -> None:
        self._observers: List[Observer] = []
        self._event_handlers: Dict[str, List[Callable]] = {}

    def attach(self, observer: Observer) -> None:
        if observer not in self._observers:
            self._observers.append(observer)
            logger.debug(f"Observer attached: {observer.__class__.__name__}")

    def detach(self, observer: Observer) -> None:
        if observer in self._observers:
            self._observers.remove(observer)
            logger.debug(f"Observer detached: {observer.__class__.__name__}")

    def on(self, event: str, handler: Callable) -> None:
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)

    def off(self, event: str, handler: Optional[Callable] = None) -> None:
        if event in self._event_handlers:
            if handler is None:
                del self._event_handlers[event]
            else:
                self._event_handlers[event] = [
                    h for h in self._event_handlers[event] if h != handler
                ]

    def notify(self, event: str, data: Any = None) -> None:
        for observer in self._observers:
            try:
                observer.update(self, event, data)
            except Exception as e:
                logger.error(f"Observer update error: {e}")

        if event in self._event_handlers:
            for handler in self._event_handlers[event]:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(f"Event handler error for {event}: {e}")
