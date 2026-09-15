from __future__ import annotations
import asyncio
import threading
import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from ..utils.logger import logger


class EventType(str, Enum):
    AUDIO_INPUT = "audio.input"
    PROCESSED_AUDIO = "audio.processed"
    GATED_AUDIO = "audio.gated"
    AUDIO_OUTPUT = "audio.output"
    WAKE_WORD_DETECTED = "audio.wake_word"
    VAD_START = "audio.vad_start"
    VAD_END = "audio.vad_end"
    AUDIO_BARGE_IN = "audio.barge_in"
    AUDIO_START_RECORDING = "audio.start_recording"
    AUDIO_STOP_RECORDING = "audio.stop_recording"
    AUDIO_OUTPUT_COMPLETE = "audio.output_complete"
    AUDIO_INTERRUPT = "audio.interrupt"

    MUSIC_PLAY = "music.play"
    MUSIC_PAUSE = "music.pause"
    MUSIC_RESUME = "music.resume"
    MUSIC_STOP = "music.stop"
    MUSIC_NEXT = "music.next"
    MUSIC_PREVIOUS = "music.previous"
    MUSIC_PREV = "music.prev"
    MUSIC_TOGGLE = "music.toggle"
    MUSIC_VOLUME = "music.volume"

    STREAM_TTS_AUDIO = "stream.tts_audio"
    STREAM_PLAY_DONE = "stream.play_done"

    VISION_FRAME = "vision.frame"
    FACE_DETECTED = "vision.face_detected"
    GESTURE_DETECTED = "vision.gesture_detected"
    DISTANCE_UPDATE = "vision.distance_update"

    NLP_TRANSCRIBE_DONE = "nlp.transcribe_done"
    NLP_RESPONSE_START = "nlp.response_start"
    NLP_RESPONSE_CHUNK = "nlp.response_chunk"
    NLP_RESPONSE_DONE = "nlp.response_done"
    NLP_SENTENCE_CHUNK = "nlp.sentence_chunk"
    INTENT_RECOGNIZED = "nlp.intent_recognized"

    DIALOG_START = "dialog.start"
    DIALOG_END = "dialog.end"
    DIALOG_STATE_CHANGED = "dialog.state_changed"

    SKILL_INVOKE = "skill.invoke"
    SKILL_RESULT = "skill.result"

    FUNCTION_CALL = "nlp.function_call"
    FUNCTION_RESULT = "nlp.function_result"

    UI_UPDATE = "ui.update"
    EINK_UPDATE = "ui.eink_update"
    MAIN_SCREEN_UPDATE = "ui.main_screen_update"

    SYSTEM_ERROR = "system.error"
    SYSTEM_STATUS = "system.status"
    SYSTEM_MODE_CHANGE = "system.mode_change"
    SYSTEM_STATE_CHANGE = "system.state_change"
    SLA_METRIC = "system.sla_metric"


@dataclass
class Event:
    event_type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: __import__("time").time())
    source: Optional[str] = None
    priority: int = 5

    def __repr__(self) -> str:
        return f"Event({self.event_type.value}, source={self.source}, id={self.event_id[:8]}...)"


class MessageBus:
    _instance: Optional["MessageBus"] = None

    def __new__(cls) -> "MessageBus":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._subscribers: Dict[EventType, List[tuple]] = {}
        self._event_history: List[Event] = []
        self._max_history = 500
        self._lock = threading.RLock()
        # [防阻塞修复] 队列最大长度从1000缩减到200，防止内存堆积
        self._queue: asyncio.PriorityQueue[Tuple[int, Event]] = asyncio.PriorityQueue(maxsize=200)
        self._queue_running = False
        self._queue_task: Optional[asyncio.Task] = None
        self._semaphore = asyncio.Semaphore(50)
        # [防阻塞修复] 记录队列溢出丢弃次数
        self._queue_discard_count = 0
        logger.info("MessageBus initialized")

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[Event], Any],
        subscriber_name: str = "unknown",
        priority: int = 5,
    ) -> str:
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []

            subscription_id = str(uuid.uuid4())
            self._subscribers[event_type].append(
                (subscription_id, callback, subscriber_name, priority)
            )
            self._subscribers[event_type].sort(key=lambda x: x[3])

        logger.debug(
            f"Subscribed: {subscriber_name} -> {event_type.value} (id={subscription_id[:8]})"
        )
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            for event_type, subscribers in self._subscribers.items():
                for i, (sid, _, _, _) in enumerate(subscribers):
                    if sid == subscription_id:
                        subscribers.pop(i)
                        logger.debug(f"Unsubscribed: {subscription_id[:8]}")
                        return True
        return False

    def publish(self, event: Event) -> None:
        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)

            subscribers = list(self._subscribers.get(event.event_type, []))

        logger.debug(
            f"Publish: {event.event_type.value} to {len(subscribers)} subscribers"
        )

        for _, callback, name, _ in subscribers:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as e:
                logger.error(f"Subscriber {name} error: {e}")

    async def publish_async(self, event: Event) -> None:
        """[防阻塞修复] 异步发布事件，带超时保护和队列溢出处理"""
        try:
            async with self._semaphore:
                # [防阻塞修复] 使用非阻塞put + 溢出丢弃策略
                try:
                    self._queue.put_nowait((event.priority, event))
                except asyncio.QueueFull:
                    # [防阻塞修复] 队列满时：丢弃低优先级事件，保留高优先级
                    if event.priority <= 3:
                        # 高优先级事件：尝试丢弃一个最低优先级事件
                        try:
                            discarded = await asyncio.wait_for(
                                self._queue.get(), timeout=0.5
                            )
                            logger.warning(
                                f"Queue full, discarded low priority event: {discarded[1].event_type.value}"
                            )
                            self._queue.put_nowait((event.priority, event))
                        except asyncio.TimeoutError:
                            logger.error(
                                f"Queue full and cannot evict, dropping event: {event.event_type.value}"
                            )
                            self._queue_discard_count += 1
                    else:
                        # 低优先级事件：直接丢弃
                        logger.warning(
                            f"Queue full, dropping low priority event: {event.event_type.value}"
                        )
                        self._queue_discard_count += 1

                if not self._queue_running:
                    self._queue_running = True
                    self._queue_task = asyncio.create_task(self._process_queue())

        except Exception as e:
            logger.error(f"Failed to publish async event: {e}")

    async def _process_queue(self) -> None:
        """[防阻塞修复] 队列处理循环，带超时保护"""
        while True:
            try:
                # [防阻塞修复] get操作带超时，防止无限等待
                _, event = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                # [防阻塞修复] 超时检查队列是否为空，避免空转
                if self._queue.empty():
                    self._queue_running = False
                    break
                continue
            except asyncio.CancelledError:
                break

            try:
                with self._lock:
                    self._event_history.append(event)
                    if len(self._event_history) > self._max_history:
                        self._event_history.pop(0)

                    subscribers = list(self._subscribers.get(event.event_type, []))

                logger.debug(
                    f"Async Publish: {event.event_type.value} to {len(subscribers)} subscribers"
                )

                for _, callback, name, _ in subscribers:
                    try:
                        result = callback(event)
                        if asyncio.iscoroutine(result):
                            # [防阻塞修复] 回调执行带超时，防止慢回调阻塞队列
                            await asyncio.wait_for(result, timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.error(f"Async callback {name} timed out")
                    except Exception as e:
                        logger.error(f"Async Subscriber {name} error: {e}")

            except Exception as e:
                logger.error(f"Error processing event {event.event_type.value}: {e}")

            finally:
                self._queue.task_done()

    def get_history(
        self, event_type: Optional[EventType] = None, limit: int = 100
    ) -> List[Event]:
        with self._lock:
            if event_type:
                filtered = [e for e in self._event_history if e.event_type == event_type]
                return list(filtered[-limit:])
            return list(self._event_history[-limit:])

    def clear_history(self) -> None:
        with self._lock:
            self._event_history.clear()

    def shutdown(self) -> None:
        if self._queue_task:
            self._queue_task.cancel()
            self._queue_task = None
        self._queue_running = False
        logger.info("MessageBus shutdown")

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return sum(len(subs) for subs in self._subscribers.values())

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def discard_count(self) -> int:
        return self._queue_discard_count