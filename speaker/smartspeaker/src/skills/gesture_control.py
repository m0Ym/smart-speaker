from __future__ import annotations
from typing import Dict, Any
from ..utils.logger import logger
from ..core.message_bus import MessageBus, Event, EventType
from ..skills.base import BaseSkill, SkillResult


class GestureControlSkill(BaseSkill):
    def __init__(self) -> None:
        super().__init__("gesture", "手势控制")
        self._last_gesture = None
        self._gesture_cooldown = 0
        self._cooldown_duration = 2

    def can_handle(self, intent: str, entities: Dict[str, Any]) -> bool:
        return intent == "gesture"

    def execute(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        gesture_type = entities.get("gesture", "")
        confidence = entities.get("confidence", 0.0)
        now = entities.get("timestamp", 0)

        if confidence < 0.7:
            return SkillResult(
                success=False,
                message=f"手势识别置信度不足: {confidence}",
            )

        if self._gesture_cooldown > now:
            return SkillResult(
                success=False,
                message="手势冷却中",
            )

        self._last_gesture = gesture_type
        self._gesture_cooldown = now + self._cooldown_duration

        speak = ""
        action = ""

        if gesture_type == "palm":
            action = "暂停/播放切换"
            speak = "已切换播放状态"
        elif gesture_type == "fist":
            action = "停止播放"
            speak = "已停止播放"
        elif gesture_type == "wave_left":
            action = "上一首"
            speak = "正在播放上一首"
        elif gesture_type == "wave_right":
            action = "下一首"
            speak = "正在播放下一首"
        elif gesture_type == "thumb_up":
            action = "音量+10%"
            speak = "音量已调大"
        elif gesture_type == "index_point":
            action = "唤醒语音助手"
            speak = "你好，有什么可以帮您的吗"
        elif gesture_type == "victory":
            action = "音量-10%"
            speak = "音量已调小"
        else:
            return SkillResult(
                success=False,
                message=f"未识别的手势: {gesture_type}",
            )

        logger.info(f"手势控制: {action} (置信度={confidence:.2f})")

        return SkillResult(
            success=True,
            data={
                "action": action,
                "gesture": gesture_type,
                "confidence": confidence,
            },
            message=f"手势{action}",
            speak_text=speak,
        )