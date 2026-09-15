from enum import Enum
from dataclasses import dataclass
from typing import Optional, Any, List, Dict, Callable
import threading
import time
from .message_bus import MessageBus, Event, EventType


class SystemState(Enum):
    IDLE = "idle"
    WAKED_UP = "waked_up"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass
class StateTransition:
    from_state: SystemState
    to_state: SystemState
    trigger: str
    timestamp: float
    data: Optional[Any] = None
    valid: bool = True


class StateMachine:
    VALID_TRANSITIONS = {
        SystemState.IDLE: [SystemState.WAKED_UP, SystemState.ERROR],
        SystemState.WAKED_UP: [SystemState.LISTENING, SystemState.IDLE, SystemState.ERROR],
        SystemState.LISTENING: [SystemState.PROCESSING, SystemState.IDLE, SystemState.WAKED_UP, SystemState.ERROR],
        SystemState.PROCESSING: [SystemState.SPEAKING, SystemState.LISTENING, SystemState.IDLE, SystemState.ERROR],
        SystemState.SPEAKING: [SystemState.IDLE, SystemState.WAKED_UP, SystemState.ERROR],
        SystemState.ERROR: [SystemState.IDLE],
    }

    def __init__(self, message_bus: MessageBus):
        self.message_bus = message_bus
        self._current_state = SystemState.IDLE
        self._state_history: List[StateTransition] = []
        self._state_lock = threading.RLock()
        self._state_listeners: List[Callable] = []
        
        self._max_listening_time = 15.0
        self._max_processing_time = 30.0
        
        self._listening_start_time: float = 0.0
        self._processing_start_time: float = 0.0
        self._monitor_running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_event = threading.Event()

        self._register_event_handlers()
        
        logger = __import__("logging").getLogger(__name__)
        logger.info("StateMachine initialized")

    def _register_event_handlers(self) -> None:
        self.message_bus.subscribe(EventType.WAKE_WORD_DETECTED, self._on_wakeword)
        self.message_bus.subscribe(EventType.VAD_START, self._on_vad_start)
        self.message_bus.subscribe(EventType.VAD_END, self._on_vad_end)
        self.message_bus.subscribe(EventType.AUDIO_OUTPUT, self._on_audio_output)
        self.message_bus.subscribe(EventType.NLP_RESPONSE_DONE, self._on_response_done)
        self.message_bus.subscribe(EventType.SYSTEM_ERROR, self._on_system_error)
        self.message_bus.subscribe(EventType.SYSTEM_STATUS, self._on_system_status)

    def _on_wakeword(self, event: Event) -> None:
        self.transition(SystemState.WAKED_UP, "wakeword_detected", event.data)

    def _on_vad_start(self, event: Event) -> None:
        self.transition(SystemState.LISTENING, "vad_start", event.data)

    def _on_vad_end(self, event: Event) -> None:
        self.transition(SystemState.PROCESSING, "vad_end", event.data)

    def _on_audio_output(self, event: Event) -> None:
        self.transition(SystemState.SPEAKING, "audio_output_start", event.data)

    def _on_response_done(self, event: Event) -> None:
        if self.is_state(SystemState.SPEAKING):
            self.transition(SystemState.IDLE, "response_done", event.data)

    def _on_system_error(self, event: Event) -> None:
        self.transition(SystemState.ERROR, "system_error", event.data)

    def _on_system_status(self, event: Event) -> None:
        status = event.data.get("status")
        if status == "shutdown":
            self._stop_monitor()

    def _validate_transition(self, new_state: SystemState) -> bool:
        with self._state_lock:
            current = self._current_state
        return new_state in self.VALID_TRANSITIONS.get(current, [])

    def _start_monitor(self) -> None:
        if self._monitor_running:
            return
        
        self._monitor_running = True
        self._monitor_event.clear()
        
        def monitor_loop():
            logger = __import__("logging").getLogger(__name__)
            while self._monitor_running:
                try:
                    with self._state_lock:
                        state = self._current_state
                        now = time.time()
                        
                        if state == SystemState.LISTENING:
                            elapsed = now - self._listening_start_time
                            if elapsed > self._max_listening_time:
                                logger.warning(f"Listening timeout after {elapsed:.1f}s")
                                self._schedule_transition(SystemState.IDLE, "listening_timeout")
                        elif state == SystemState.PROCESSING:
                            elapsed = now - self._processing_start_time
                            if elapsed > self._max_processing_time:
                                logger.warning(f"Processing timeout after {elapsed:.1f}s")
                                self._schedule_transition(SystemState.ERROR, "processing_timeout")
                except Exception as e:
                    logger.error(f"State monitor error: {e}")
                
                self._monitor_event.wait(0.5)
        
        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _stop_monitor(self) -> None:
        self._monitor_running = False
        self._monitor_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)
            self._monitor_thread = None

    def _schedule_transition(self, new_state: SystemState, trigger: str, data: Optional[Any] = None) -> None:
        threading.Thread(
            target=self.transition,
            args=(new_state, trigger, data),
            daemon=True
        ).start()

    def _start_listening_timeout(self) -> None:
        with self._state_lock:
            self._listening_start_time = time.time()
        self._start_monitor()

    def _start_processing_timeout(self) -> None:
        with self._state_lock:
            self._processing_start_time = time.time()
        self._start_monitor()

    def _cancel_timeouts(self) -> None:
        pass

    def transition(self, new_state: SystemState, trigger: str, data: Optional[Any] = None):
        logger = __import__("logging").getLogger(__name__)

        with self._state_lock:
            if self._current_state == new_state:
                return

            old_state = self._current_state
            is_valid = new_state in self.VALID_TRANSITIONS.get(old_state, [])

            transition = StateTransition(
                from_state=old_state,
                to_state=new_state,
                trigger=trigger,
                timestamp=time.time(),
                data=data,
                valid=is_valid,
            )

            if not is_valid:
                logger.warning(f"Invalid state transition: {old_state.value} -> {new_state.value}")
                return

            self._state_history.append(transition)
            self._current_state = new_state

            if new_state == SystemState.LISTENING:
                self._listening_start_time = time.time()
            elif new_state == SystemState.PROCESSING:
                self._processing_start_time = time.time()

            if len(self._state_history) > 100:
                self._state_history = self._state_history[-100:]

        self._handle_state_timers(new_state)

        self.message_bus.publish(Event(
            event_type=EventType.DIALOG_STATE_CHANGED,
            data={
                "from_state": old_state.value,
                "to_state": new_state.value,
                "trigger": trigger,
                "timestamp": transition.timestamp,
                "data": data,
            }
        ))

        for listener in self._state_listeners:
            try:
                listener(old_state, new_state, trigger, data)
            except Exception as e:
                logger.error(f"State listener error: {e}")

    def _handle_state_timers(self, new_state: SystemState) -> None:
        if new_state == SystemState.LISTENING:
            self._start_listening_timeout()
        elif new_state == SystemState.PROCESSING:
            self._start_processing_timeout()

    def recover_from_error(self, data: Optional[Any] = None) -> None:
        logger = __import__("logging").getLogger(__name__)
        logger.info("Attempting to recover from error state")
        self.transition(SystemState.IDLE, "error_recovery", data)

    def force_transition(self, new_state: SystemState, trigger: str, data: Optional[Any] = None) -> None:
        logger = __import__("logging").getLogger(__name__)
        logger.warning(f"Forcing transition: {self._current_state.value} -> {new_state.value}")
        
        with self._state_lock:
            old_state = self._current_state
            transition = StateTransition(
                from_state=old_state,
                to_state=new_state,
                trigger=trigger,
                timestamp=time.time(),
                data=data,
                valid=True,
            )
            self._state_history.append(transition)
            self._current_state = new_state

            if new_state == SystemState.LISTENING:
                self._listening_start_time = time.time()
            elif new_state == SystemState.PROCESSING:
                self._processing_start_time = time.time()

            if len(self._state_history) > 100:
                self._state_history = self._state_history[-100:]

        self._handle_state_timers(new_state)

        self.message_bus.publish(Event(
            event_type=EventType.DIALOG_STATE_CHANGED,
            data={
                "from_state": old_state.value,
                "to_state": new_state.value,
                "trigger": trigger,
                "timestamp": transition.timestamp,
                "data": data,
            }
        ))

    def add_state_listener(self, listener: Callable) -> None:
        with self._state_lock:
            self._state_listeners.append(listener)

    def remove_state_listener(self, listener: Callable) -> None:
        with self._state_lock:
            if listener in self._state_listeners:
                self._state_listeners.remove(listener)

    def get_current_state(self) -> SystemState:
        with self._state_lock:
            return self._current_state

    def is_state(self, state: SystemState) -> bool:
        with self._state_lock:
            return self._current_state == state

    @property
    def current_state(self) -> SystemState:
        with self._state_lock:
            return self._current_state

    def get_state_history(self, limit: int = 20) -> List[StateTransition]:
        with self._state_lock:
            return list(self._state_history[-limit:])

    def can_transition_to(self, state: SystemState) -> bool:
        with self._state_lock:
            return state in self.VALID_TRANSITIONS.get(self._current_state, [])

    def shutdown(self) -> None:
        self._stop_monitor()
        logger = __import__("logging").getLogger(__name__)
        logger.info("StateMachine shutdown")
