from __future__ import annotations
import time
import threading
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, field
from ..utils.logger import logger

from ..core.message_bus import MessageBus, Event, EventType
from ..core.observer import Subject, Observer
from ..core.strategy import StrategyManager
from ..skills.base import BaseSkill, SkillResult
from ..skills.factory import SkillFactory
from ..nlp.processor import IntentResult


class DialogState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    RESPONDING = "responding"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass
class DialogSession:
    session_id: str
    state: DialogState = DialogState.IDLE
    start_time: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    turn_count: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def add_turn(self, user_text: str, assistant_text: str, intent: str) -> None:
        self.turn_count += 1
        self.last_activity = time.time()
        self.history.append(
            {
                "turn": self.turn_count,
                "user": user_text,
                "assistant": assistant_text,
                "intent": intent,
                "timestamp": time.time(),
            }
        )


class DialogManager(Subject):
    def __init__(self, bus: MessageBus) -> None:
        super().__init__()
        self._bus = bus
        self._running = False
        self._current_session: Optional[DialogSession] = None
        self._skill_factory = SkillFactory()
        self._skills: Dict[str, BaseSkill] = {}
        self._route_strategy = StrategyManager()

        self._init_skills()
        self._subscribe_events()
        logger.info("DialogManager initialized")

    def _init_skills(self) -> None:
        self._skills = self._skill_factory.create_all()
        logger.info(f"Loaded {len(self._skills)} skills: {list(self._skills.keys())}")

    def _subscribe_events(self) -> None:
        self._bus.subscribe(
            EventType.WAKE_WORD_DETECTED,
            self._on_wake_word,
            "dialog_manager",
            priority=2,
        )
        self._bus.subscribe(
            EventType.INTENT_RECOGNIZED,
            self._on_intent_recognized,
            "dialog_manager",
            priority=2,
        )
        self._bus.subscribe(
            EventType.GESTURE_DETECTED,
            self._on_gesture_detected,
            "dialog_manager",
            priority=3,
        )
        self._bus.subscribe(
            EventType.NLP_SENTENCE_CHUNK,
            self._on_sentence_chunk,
            "dialog_manager",
            priority=1,
        )
        self._bus.subscribe(
            EventType.NLP_RESPONSE_DONE,
            self._on_response_done,
            "dialog_manager",
            priority=2,
        )
        self._bus.subscribe(
            EventType.AUDIO_INTERRUPT,
            self._on_interrupt,
            "dialog_manager",
            priority=1,
        )
        self._bus.subscribe(
            EventType.AUDIO_OUTPUT_COMPLETE,
            self._on_audio_complete,
            "dialog_manager",
            priority=2,
        )
        self._bus.subscribe(
            EventType.SYSTEM_STATUS,
            self._on_system_status,
            "dialog_manager",
        )

    def _on_system_status(self, event: Event) -> None:
        status = event.data.get("status")
        if status == "shutdown":
            self.stop()

    def _on_interrupt(self, event: Event) -> None:
        reason = event.data.get("reason", "unknown")
        logger.info(f"Dialog interrupt received: {reason}")
        
        if self._current_session:
            self._set_state(DialogState.IDLE)
            self._end_session()
        else:
            self._set_state(DialogState.IDLE)
        
        self.notifyObservers()

    def _on_sentence_chunk(self, event: Event) -> None:
        text = event.data.get("text", "")
        if not text:
            return

        logger.info(f"Processing sentence chunk: '{text}'")
        self._set_state(DialogState.SPEAKING)
        self.notifyObservers()

        self._bus.publish(Event(
            event_type=EventType.AUDIO_OUTPUT,
            data={"text": text, "intent": "llm_chat", "stream_chunk": True},
            source="DialogManager",
        ))

        self._bus.publish(Event(
            event_type=EventType.UI_UPDATE,
            data={"type": "skill_result", "skill": "llm", "data": {"response": text}, "speak_text": text},
            source="DialogManager",
        ))

    def _on_wake_word(self, event: Event) -> None:
        confidence = event.data.get("confidence", 0)
        self.routeIntent("wake_word", {"confidence": confidence})

    def _on_gesture_detected(self, event: Event) -> None:
        gesture = event.data.get("gesture", "")
        confidence = event.data.get("confidence", 0)
        timestamp = event.data.get("timestamp", 0)

        logger.info(f"Gesture detected: {gesture} (conf={confidence:.2f})")

        if confidence >= 0.7:
            self.applyStrategy("gesture", {
                "gesture": gesture,
                "confidence": confidence,
                "timestamp": timestamp,
            }, "")

    def _on_intent_recognized(self, event: Event) -> None:
        intent = event.data.get("intent", "unknown")
        text = event.data.get("text", "")
        entities = event.data.get("entities", {})
        confidence = event.data.get("confidence", 0)

        # 防御性检查：空文本不处理，避免空白内容触发回答
        if not text or not text.strip():
            logger.debug("Empty text in intent, ignoring")
            return

        logger.info(f"Intent recognized: {intent} (conf={confidence:.2f})")

        # 语音退出指令处理
        if intent == "exit":
            logger.info("收到退出指令，正在关闭系统...")
            self._set_state(DialogState.IDLE)
            self.notifyObservers()
            self._bus.publish(
                Event(
                    event_type=EventType.AUDIO_OUTPUT,
                    data={"text": "好的，再见！", "skill": "exit", "intent": "exit"},
                    source="DialogManager",
                )
            )
            # 延迟发布 shutdown 事件，让 TTS 播放完再见语
            def _delayed_shutdown():
                import time
                time.sleep(3.0)
                self._bus.publish(
                    Event(
                        event_type=EventType.SYSTEM_STATUS,
                        data={"status": "shutdown", "source": "voice_exit"},
                        source="DialogManager",
                    )
                )
            threading.Thread(target=_delayed_shutdown, daemon=True).start()
            return

        if self._current_session:
            self._current_session.context["last_user_text"] = text

        self.applyStrategy(intent, entities, text)

    def _on_response_done(self, event: Event) -> None:
        text = event.data.get("text", "")
        intent = event.data.get("intent", "")

        if self._current_session:
            last_user = self._current_session.context.get("last_user_text", "")
            self._current_session.add_turn(last_user, text, intent)

        # 设置为RESPONDING状态，等待AUDIO_OUTPUT_COMPLETE事件重置为IDLE
        self._set_state(DialogState.RESPONDING)
        self.notifyObservers()

    def _on_audio_complete(self, event: Event) -> None:
        """音频输出完成后重置对话状态为IDLE

        修复bug：之前没有订阅此事件，导致状态一直停留在RESPONDING/SPEAKING，
        UI长时间显示"响应中"。
        """
        if self._current_session:
            current_state = self._current_session.state
            if current_state in (DialogState.RESPONDING, DialogState.SPEAKING,
                                 DialogState.PROCESSING):
                self._set_state(DialogState.IDLE)
                self.notifyObservers()
                logger.debug("[Dialog] 音频输出完成，状态重置为IDLE")

    def routeIntent(self, intent: str, data: Dict[str, Any]) -> None:
        if intent == "wake_word":
            self._start_session()
            self._set_state(DialogState.LISTENING)
            self.notifyObservers()
            self._bus.publish(
                Event(
                    event_type=EventType.DIALOG_START,
                    data={"timestamp": time.time()},
                    source="DialogManager",
                )
            )
            logger.info("Dialog session started")

        self.notify("intent_routed", {"intent": intent, "data": data})

    def applyStrategy(
        self, intent: str, entities: Dict[str, Any], text: str
    ) -> Optional[SkillResult]:
        if not self._current_session:
            self._start_session()

        self._set_state(DialogState.PROCESSING)
        self.notifyObservers()
        if self._current_session:
            self._current_session.context["last_intent"] = intent

        skill = self._find_skill(intent, entities)
        if skill and skill.enabled:
            self._bus.publish(
                Event(
                    event_type=EventType.SKILL_INVOKE,
                    data={"skill": skill.name, "intent": intent},
                    source="DialogManager",
                )
            )

            context = self._current_session.context if self._current_session else {}
            entities_copy = {**entities, "text": text}

            def execute_skill_async():
                try:
                    result = skill.execute(intent, entities_copy, context)
                    self._handle_skill_result(skill.name, result, intent)
                except Exception as e:
                    logger.error(f"Skill execution error: {e}")
                    error_result = SkillResult(success=False, speak_text="抱歉，执行技能时出现错误。")
                    self._handle_skill_result(skill.name, error_result, intent)

            threading.Thread(target=execute_skill_async, daemon=True).start()

            return None

        # 没有找到匹配的技能，发送兜底回复
        logger.warning(f"No skill found for intent: {intent}")
        self._set_state(DialogState.RESPONDING)
        self.notifyObservers()
        fallback_text = "抱歉，我不太明白您的意思。您可以问我天气、音乐、闹钟、笑话等问题。"
        self._bus.publish(
            Event(
                event_type=EventType.AUDIO_OUTPUT,
                data={"text": fallback_text, "skill": "fallback", "intent": intent},
                source="DialogManager",
            )
        )
        return None

    def _handle_skill_result(self, skill_name: str, result: SkillResult, intent: str) -> None:
        self._bus.publish(
            Event(
                event_type=EventType.SKILL_RESULT,
                data={
                    "skill": skill_name,
                    "success": result.success,
                    "message": result.message,
                    "speak_text": result.speak_text,
                },
                source="DialogManager",
            )
        )

        self._set_state(DialogState.RESPONDING)
        self.notifyObservers()

        if result.speak_text:
            audio_data = {"text": result.speak_text, "skill": skill_name, "intent": intent}
            if result.data and result.data.get("song_path"):
                audio_data["song_path"] = result.data["song_path"]
            self._bus.publish(
                Event(
                    event_type=EventType.AUDIO_OUTPUT,
                    data=audio_data,
                    source="DialogManager",
                )
            )
            self._bus.publish(
                Event(
                    event_type=EventType.UI_UPDATE,
                    data={
                        "type": "skill_result",
                        "skill": skill_name,
                        "data": result.data,
                        "speak_text": result.speak_text,
                    },
                    source="DialogManager",
                )
            )
            # 技能有回复内容，直接返回，不再走 fallback
            return

        # 技能无回复内容时，发送兜底回复
        if not result.success:
            logger.warning(f"Skill {skill_name} failed for intent: {intent}")
            fallback_text = result.speak_text or "抱歉，我不太明白您的意思。您可以问我天气、音乐、闹钟、笑话等问题。"
            self._bus.publish(
                Event(
                    event_type=EventType.AUDIO_OUTPUT,
                    data={"text": fallback_text, "skill": "fallback", "intent": intent},
                    source="DialogManager",
                )
            )
        else:
            # 修复bug：success=True但speak_text为空（如音乐冷却），给用户明确反馈
            logger.info(f"Skill {skill_name} succeeded but no speak_text, sending idle hint")
            # 不发TTS避免噪音，但重置状态为IDLE
            if self._current_session:
                self._set_state(DialogState.IDLE)
                self.notifyObservers()

    def createSkill(self, name: str) -> Optional[BaseSkill]:
        return self._skill_factory.create_skill(name)

    def notifyObservers(self) -> None:
        state = self._current_session.state if self._current_session else DialogState.IDLE
        self.notify("state_changed", state)
        self._bus.publish(
            Event(
                event_type=EventType.DIALOG_STATE_CHANGED,
                data={"state": state.value},
                source="DialogManager",
            )
        )

    def _find_skill(
        self, intent: str, entities: Dict[str, Any]
    ) -> Optional[BaseSkill]:
        function_skill_mapping = {
            "query_weather": "weather",
            "control_music": "music",
            "set_alarm": "alarm",
            "tell_joke": "joke",
            "chat": "chat",
            "control_device": "smarthome",
            "toggle_device": "smarthome",
            "smarthome": "smarthome",
            "system_command": "system_command",
        }
        
        mapped_intent = function_skill_mapping.get(intent, intent)
        
        for skill in self._skills.values():
            if skill.enabled and skill.can_handle(mapped_intent, entities):
                return skill
        return None

    def _start_session(self) -> DialogSession:
        import uuid

        session = DialogSession(session_id=str(uuid.uuid4()))
        self._current_session = session
        return session

    def _end_session(self) -> None:
        if self._current_session:
            self._bus.publish(
                Event(
                    event_type=EventType.DIALOG_END,
                    data={
                        "session_id": self._current_session.session_id,
                        "turn_count": self._current_session.turn_count,
                        "duration": time.time() - self._current_session.start_time,
                    },
                    source="DialogManager",
                )
            )
            logger.info(
                f"Dialog session ended: turns={self._current_session.turn_count}"
            )
        self._current_session = None
        self._set_state(DialogState.IDLE)

    def _set_state(self, state: DialogState) -> None:
        if self._current_session:
            old_state = self._current_session.state
            self._current_session.state = state
            if old_state != state:
                logger.debug(f"Dialog state: {old_state.value} -> {state.value}")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info("DialogManager started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._end_session()
        for skill in self._skills.values():
            skill.cleanup()
        logger.info("DialogManager stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_state(self) -> DialogState:
        if self._current_session:
            return self._current_session.state
        return DialogState.IDLE

    @property
    def current_session(self) -> Optional[DialogSession]:
        return self._current_session

    @property
    def available_skills(self) -> List[str]:
        return [s.name for s in self._skills.values() if s.enabled]

    @property
    def all_skills(self) -> Dict[str, BaseSkill]:
        return dict(self._skills)
