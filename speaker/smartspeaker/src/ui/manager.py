from __future__ import annotations
from typing import Any, Optional
from ..utils.logger import logger

from ..core.message_bus import MessageBus, Event, EventType
from ..core.observer import Subject, Observer
from ..config import UIConfig
from .base import UIState
from .main_screen import MainScreen
from .eink_screen import EInkScreen, EinkMode


class UIManager(Subject, Observer):
    def __init__(self, config: UIConfig, bus: MessageBus) -> None:
        super().__init__()
        self._config = config
        self._bus = bus
        self._main_screen: Optional[MainScreen] = None
        self._eink_screen: Optional[EInkScreen] = None
        self._running = False

        self._init_screens()
        logger.info("UIManager initialized")

    def _init_screens(self) -> None:
        self._main_screen = MainScreen(self._config, self._bus)
        self._eink_screen = EInkScreen(self._config, self._bus)

        self.attach(self._main_screen)
        self.attach(self._eink_screen)

    def update_screens(self, **kwargs) -> None:
        if self._main_screen:
            self._main_screen.update_state(**kwargs)
        if self._eink_screen:
            self._eink_screen.update_state(**kwargs)

    def show_notification(self, text: str, duration: float = 3.0) -> None:
        if self._main_screen:
            self._main_screen.show_notification(text, duration)
        if self._eink_screen:
            self._eink_screen.set_mode(EinkMode.NOTIFICATION)

    def set_eink_mode(self, mode: EinkMode) -> None:
        if self._eink_screen:
            self._eink_screen.set_mode(mode)

    def set_main_page(self, page: str) -> bool:
        if self._main_screen:
            return self._main_screen.show_page(page)
        return False

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        if self._main_screen:
            self._main_screen.enabled = True
            self._main_screen.render()
        if self._eink_screen:
            self._eink_screen.enabled = True
            self._eink_screen.render()

        logger.info("UIManager started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._main_screen:
            self._main_screen.enabled = False
        if self._eink_screen:
            self._eink_screen.enabled = False

        logger.info("UIManager stopped")

    def update(self, subject, event: str, data: Any = None) -> None:
        if event == "state_changed":
            if self._main_screen:
                self._main_screen.update_state(dialog_state=data.value if hasattr(data, 'value') else str(data))
            if self._eink_screen:
                self._eink_screen.update_state(dialog_state=data.value if hasattr(data, 'value') else str(data))
        elif event == "response_done":
            pass

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def main_screen(self) -> Optional[MainScreen]:
        return self._main_screen

    @property
    def eink_screen(self) -> Optional[EInkScreen]:
        return self._eink_screen
