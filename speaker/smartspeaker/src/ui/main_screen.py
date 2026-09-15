from __future__ import annotations
from typing import Any, Dict, Optional
from ..utils.logger import logger

from .base import BaseScreen, UIState
from ..core.message_bus import MessageBus, Event, EventType
from ..config import UIConfig


class MainScreen(BaseScreen):
    def __init__(self, config: UIConfig, bus: MessageBus) -> None:
        super().__init__("main_screen")
        self._config = config
        self._bus = bus
        self._pages = ["home", "weather", "music", "smart_home", "settings"]
        self._current_page = "home"
        self._cards: Dict[str, Any] = {}

        self._subscribe_events()
        logger.info("MainScreen initialized")

    def _subscribe_events(self) -> None:
        self._bus.subscribe(
            EventType.UI_UPDATE,
            self._on_ui_update,
            "main_screen",
        )
        self._bus.subscribe(
            EventType.DIALOG_STATE_CHANGED,
            self._on_dialog_state,
            "main_screen",
        )
        self._bus.subscribe(
            EventType.DISTANCE_UPDATE,
            self._on_distance_update,
            "main_screen",
        )
        self._bus.subscribe(
            EventType.WAKE_WORD_DETECTED,
            self._on_wake_word,
            "main_screen",
        )

    def _on_ui_update(self, event: Event) -> None:
        update_type = event.data.get("type", "")
        data = event.data.get("data", {})
        speak_text = event.data.get("speak_text", "")

        if update_type == "skill_result":
            skill = event.data.get("skill", "")
            self.update_state(
                current_skill=skill,
                last_text=speak_text,
            )
            self._update_skill_card(skill, data)

    def _on_dialog_state(self, event: Event) -> None:
        state = event.data.get("state", "idle")
        self.update_state(dialog_state=state)

    def _on_distance_update(self, event: Event) -> None:
        distance = event.data.get("distance", 0)
        self.update_state(distance=distance)

    def _on_wake_word(self, event: Event) -> None:
        self.update_state(notification="我在听...")

    def _handle_event(self, event: str, data: Any = None) -> None:
        logger.debug(f"MainScreen event: {event}")

    def _update_skill_card(self, skill: str, data: Dict[str, Any]) -> None:
        self._cards[skill] = data
        logger.debug(f"Skill card updated: {skill}")

    def render(self) -> None:
        if not self._enabled:
            return

        width = self._config.main_screen_width
        height = self._config.main_screen_height
        state = self._state

        self._bus.publish(
            Event(
                event_type=EventType.MAIN_SCREEN_UPDATE,
                data={
                    "page": self._current_page,
                    "state": state.dialog_state,
                    "skill": state.current_skill,
                    "text": state.last_text,
                    "distance": state.distance,
                    "width": width,
                    "height": height,
                },
                source="MainScreen",
            )
        )

    def show_page(self, page: str) -> bool:
        if page in self._pages:
            self._current_page = page
            self.render()
            return True
        return False

    def show_notification(self, text: str, duration: float = 3.0) -> None:
        self.update_state(notification=text)

    @property
    def current_page(self) -> str:
        return self._current_page

    @property
    def available_pages(self) -> list[str]:
        return list(self._pages)
