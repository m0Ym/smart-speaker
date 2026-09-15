from __future__ import annotations
from typing import Any, Dict, List, Optional
from enum import Enum
import numpy as np
from ..utils.logger import logger

from .base import BaseScreen, UIState
from ..core.message_bus import MessageBus, Event, EventType
from ..config import UIConfig


class EinkMode(str, Enum):
    CLOCK = "clock"
    STATUS = "status"
    WEATHER = "weather"
    EMOTION = "emotion"
    NOTIFICATION = "notification"


class EInkScreen(BaseScreen):
    def __init__(self, config: UIConfig, bus: MessageBus) -> None:
        super().__init__("eink_screen")
        self._config = config
        self._bus = bus
        self._current_mode = EinkMode.CLOCK
        self._emotion = "neutral"
        self._status_icons: Dict[str, bool] = {
            "wifi": True,
            "bluetooth": False,
            "battery": True,
            "mic": True,
        }
        self._last_update = 0.0
        
        self._eink_driver = None
        self._spi_bus = config.eink_spi_bus
        self._spi_device = config.eink_spi_device
        self._driver_initialized = False
        self._driver_tried = False

        self._subscribe_events()
        logger.info("EInkScreen initialized")

    def _init_driver(self) -> bool:
        if self._driver_initialized:
            return True
        if self._driver_tried:
            return False
        self._driver_tried = True
        
        try:
            from waveshare_epd import epd2in13_V3
            
            self._eink_driver = epd2in13_V3.EPD()
            self._eink_driver.init()
            self._eink_driver.Clear()
            self._driver_initialized = True
            logger.info("E-Ink driver initialized (Waveshare 2.13 inch V3)")
            return True
        except ImportError:
            logger.warning("waveshare-epd not installed, using mock mode")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize E-Ink driver: {e}")
            return False

    def _subscribe_events(self) -> None:
        self._bus.subscribe(
            EventType.DIALOG_STATE_CHANGED,
            self._on_dialog_state,
            "eink_screen",
        )
        self._bus.subscribe(
            EventType.WAKE_WORD_DETECTED,
            self._on_wake_word,
            "eink_screen",
        )
        self._bus.subscribe(
            EventType.NLP_RESPONSE_CHUNK,
            self._on_response,
            "eink_screen",
        )
        self._bus.subscribe(
            EventType.DISTANCE_UPDATE,
            self._on_distance_update,
            "eink_screen",
        )
        self._bus.subscribe(
            EventType.SYSTEM_ERROR,
            self._on_error,
            "eink_screen",
        )

    def _on_dialog_state(self, event: Event) -> None:
        state = event.data.get("state", "idle")
        self.update_state(dialog_state=state)

        if state == "listening":
            self._set_emotion("listening")
        elif state == "processing":
            self._set_emotion("thinking")
        elif state == "responding":
            self._set_emotion("speaking")
        else:
            self._set_emotion("neutral")

    def _on_wake_word(self, event: Event) -> None:
        self._current_mode = EinkMode.EMOTION
        self._set_emotion("happy")
        self.render()

    def _on_response(self, event: Event) -> None:
        text = event.data.get("chunk", "")
        if text:
            self.update_state(last_text=text)

    def _on_distance_update(self, event: Event) -> None:
        distance = event.data.get("distance", 0)
        self.update_state(distance=distance)

    def _on_error(self, event: Event) -> None:
        error = event.data.get("message", "错误")
        self._current_mode = EinkMode.NOTIFICATION
        self.update_state(notification=error)
        self._set_emotion("sad")
        self.render()

    def _handle_event(self, event: str, data: Any = None) -> None:
        logger.debug(f"EInkScreen event: {event}")

    def _set_emotion(self, emotion: str) -> None:
        self._emotion = emotion

    def _generate_emotion_image(self, emotion: str) -> np.ndarray:
        width = self._config.eink_screen_width
        height = self._config.eink_screen_height
        
        image = np.ones((height, width), dtype=np.uint8) * 255
        
        cx, cy = width // 2, height // 2
        face_radius = min(width, height) // 3
        
        for y in range(height):
            for x in range(width):
                dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                if dist < face_radius:
                    image[y, x] = 0
        
        eye_size = face_radius // 5
        eye_offset = face_radius // 3
        
        emotions = {
            "happy": {"eye_y": -eye_offset, "eye_scale": 1.0, "mouth": "smile"},
            "sad": {"eye_y": eye_offset, "eye_scale": 0.8, "mouth": "frown"},
            "neutral": {"eye_y": 0, "eye_scale": 1.0, "mouth": "neutral"},
            "listening": {"eye_y": -eye_offset, "eye_scale": 1.2, "mouth": "neutral"},
            "thinking": {"eye_y": eye_offset // 2, "eye_scale": 1.0, "mouth": "smile_small"},
            "speaking": {"eye_y": 0, "eye_scale": 1.0, "mouth": "open"},
            "surprised": {"eye_y": -eye_offset, "eye_scale": 1.5, "mouth": "open_small"},
        }
        
        config = emotions.get(emotion, emotions["neutral"])
        
        for ex in [-1, 1]:
            eye_x = cx + ex * eye_offset
            eye_y = cy + config["eye_y"]
            for y in range(height):
                for x in range(width):
                    dist = np.sqrt((x - eye_x) ** 2 + (y - eye_y) ** 2)
                    if dist < eye_size * config["eye_scale"]:
                        image[y, x] = 255
        
        mouth_y = cy + face_radius // 2
        
        if config["mouth"] == "smile":
            for x in range(cx - face_radius // 2, cx + face_radius // 2):
                y = int(mouth_y + 5 * np.sin((x - cx) * np.pi / (face_radius // 2)))
                if 0 <= y < height:
                    image[y, x] = 255
        elif config["mouth"] == "frown":
            for x in range(cx - face_radius // 2, cx + face_radius // 2):
                y = int(mouth_y - 5 * np.sin((x - cx) * np.pi / (face_radius // 2)))
                if 0 <= y < height:
                    image[y, x] = 255
        elif config["mouth"] == "open":
            for y in range(mouth_y - eye_size // 2, mouth_y + eye_size // 2):
                for x in range(cx - eye_size, cx + eye_size):
                    if 0 <= y < height and 0 <= x < width:
                        image[y, x] = 255
        elif config["mouth"] == "open_small":
            for y in range(mouth_y - eye_size // 4, mouth_y + eye_size // 4):
                for x in range(cx - eye_size // 2, cx + eye_size // 2):
                    if 0 <= y < height and 0 <= x < width:
                        image[y, x] = 255
        elif config["mouth"] == "smile_small":
            for x in range(cx - face_radius // 4, cx + face_radius // 4):
                y = int(mouth_y + 3 * np.sin((x - cx) * np.pi / (face_radius // 4)))
                if 0 <= y < height:
                    image[y, x] = 255
        
        return image

    def _update_display(self, image: np.ndarray) -> None:
        if not self._config.eink_enabled:
            return
        
        if self._init_driver() and self._eink_driver:
            try:
                from PIL import Image
                
                img = Image.fromarray(image, mode="L")
                img = img.rotate(180)
                
                self._eink_driver.display(self._eink_driver.getbuffer(img))
                logger.debug("E-Ink display updated")
            except Exception as e:
                logger.error(f"E-Ink display update error: {e}")
        else:
            logger.debug(f"E-Ink mock update: emotion={self._emotion}, mode={self._current_mode.value}")

    def render(self) -> None:
        if not self._enabled:
            return

        width = self._config.eink_screen_width
        height = self._config.eink_screen_height

        image = self._generate_emotion_image(self._emotion)
        self._update_display(image)

        self._bus.publish(
            Event(
                event_type=EventType.EINK_UPDATE,
                data={
                    "mode": self._current_mode.value,
                    "emotion": self._emotion,
                    "status_icons": self._status_icons,
                    "text": self._state.last_text[:20] if self._state.last_text else "",
                    "dialog_state": self._state.dialog_state,
                    "distance": self._state.distance,
                    "width": width,
                    "height": height,
                },
                source="EInkScreen",
            )
        )

    def set_mode(self, mode: EinkMode) -> None:
        self._current_mode = mode
        self.render()

    def set_status(self, icon: str, value: bool) -> None:
        if icon in self._status_icons:
            self._status_icons[icon] = value
            self.render()

    def cleanup(self) -> None:
        if self._eink_driver:
            try:
                self._eink_driver.sleep()
                logger.info("E-Ink driver put to sleep")
            except Exception as e:
                logger.error(f"E-Ink cleanup error: {e}")

    @property
    def current_mode(self) -> EinkMode:
        return self._current_mode

    @property
    def current_emotion(self) -> str:
        return self._emotion
