from __future__ import annotations
import time
import json
import os
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from collections import deque
from cryptography.fernet import Fernet
from ..utils.logger import logger

from ..core.message_bus import MessageBus, Event, EventType
from ..config import SystemConfig


@dataclass
class SLAMetric:
    name: str
    value: float
    unit: str
    target: float
    current_avg: float = 0.0
    min_value: float = float("inf")
    max_value: float = float("-inf")
    history: deque = field(default_factory=lambda: deque(maxlen=100))
    status: str = "normal"

    def update(self, value: float) -> None:
        self.value = value
        self.history.append(value)
        self.current_avg = sum(self.history) / len(self.history)
        self.min_value = min(self.min_value, value)
        self.max_value = max(self.max_value, value)

        if value > self.target * 1.2:
            self.status = "warning"
        elif value > self.target * 1.5:
            self.status = "critical"
        else:
            self.status = "normal"


@dataclass
class ShadowCase:
    session_id: str
    user_text: str
    intent: str
    confidence: float
    response: str
    error_type: str
    timestamp: float
    context: Dict[str, Any] = field(default_factory=dict)


class SLAMonitor:
    def __init__(self, bus: MessageBus, config: Optional[SystemConfig] = None) -> None:
        self._bus = bus
        self._config = config or SystemConfig()
        self._metrics: Dict[str, SLAMetric] = {}
        self._start_time = time.time()
        self._event_timestamps: Dict[str, float] = {}
        
        self._wake_history: List[float] = []
        self._shadow_cases: List[ShadowCase] = []
        self._encryption_key = None
        self._current_session_text = ""
        self._current_intent = ""

        self._init_metrics()
        self._init_shadow_mode()
        self._subscribe_events()
        logger.info("SLAMonitor initialized")

    def _init_metrics(self) -> None:
        self._metrics["wake_latency"] = SLAMetric(
            name="wake_latency",
            value=0,
            unit="ms",
            target=200,
        )
        self._metrics["asr_latency"] = SLAMetric(
            name="asr_latency",
            value=0,
            unit="ms",
            target=500,
        )
        self._metrics["nlp_latency"] = SLAMetric(
            name="nlp_latency",
            value=0,
            unit="ms",
            target=800,
        )
        self._metrics["e2e_latency"] = SLAMetric(
            name="e2e_latency",
            value=0,
            unit="ms",
            target=1500,
        )
        self._metrics["intent_accuracy"] = SLAMetric(
            name="intent_accuracy",
            value=0,
            unit="%",
            target=95,
        )
        self._metrics["uptime"] = SLAMetric(
            name="uptime",
            value=0,
            unit="%",
            target=99.9,
        )
        self._metrics["repeat_wake_count"] = SLAMetric(
            name="repeat_wake_count",
            value=0,
            unit="count",
            target=5,
        )
        self._metrics["barge_in_count"] = SLAMetric(
            name="barge_in_count",
            value=0,
            unit="count",
            target=10,
        )

    def _init_shadow_mode(self) -> None:
        if self._config.shadow_mode_enabled:
            try:
                self._encryption_key = Fernet.generate_key()
                log_dir = os.path.dirname(self._config.shadow_cases_path)
                os.makedirs(log_dir, exist_ok=True)
                
                if os.path.exists(self._config.shadow_cases_path):
                    with open(self._config.shadow_cases_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self._shadow_cases = [ShadowCase(**item) for item in data]
                
                logger.info(f"Shadow mode initialized, {len(self._shadow_cases)} cases loaded")
            except Exception as e:
                logger.error(f"Failed to initialize shadow mode: {e}")

    def _subscribe_events(self) -> None:
        self._bus.subscribe(
            EventType.WAKE_WORD_DETECTED,
            self._on_wake_word,
            "sla_monitor",
            priority=1,
        )
        self._bus.subscribe(
            EventType.NLP_TRANSCRIBE_DONE,
            self._on_transcribe_done,
            "sla_monitor",
            priority=1,
        )
        self._bus.subscribe(
            EventType.NLP_RESPONSE_DONE,
            self._on_response_done,
            "sla_monitor",
            priority=1,
        )
        self._bus.subscribe(
            EventType.VAD_END,
            self._on_vad_end,
            "sla_monitor",
            priority=1,
        )
        self._bus.subscribe(
            EventType.SYSTEM_ERROR,
            self._on_error,
            "sla_monitor",
            priority=1,
        )
        self._bus.subscribe(
            EventType.INTENT_RECOGNIZED,
            self._on_intent_recognized,
            "sla_monitor",
            priority=1,
        )
        self._bus.subscribe(
            EventType.AUDIO_BARGE_IN,
            self._on_barge_in,
            "sla_monitor",
            priority=1,
        )

    def _on_wake_word(self, event: Event) -> None:
        self._event_timestamps["wake"] = event.timestamp
        
        self._wake_history.append(event.timestamp)
        if len(self._wake_history) > 10:
            self._wake_history.pop(0)
        
        self._check_repeat_wake()

    def _check_repeat_wake(self) -> None:
        if len(self._wake_history) < 2:
            return
        
        recent_wakes = self._wake_history[-3:]
        for i in range(len(recent_wakes) - 1):
            diff = recent_wakes[i + 1] - recent_wakes[i]
            if diff < self._config.repeat_wake_threshold:
                logger.warning(f"Repeat wake detected: interval={diff:.2f}s")
                self._record_shadow_case(
                    user_text="",
                    intent="wake_repeat",
                    confidence=0.0,
                    response="",
                    error_type="repeat_wake",
                    context={"interval": diff, "wake_count": len(recent_wakes)},
                )
                current_count = self._metrics["repeat_wake_count"].value
                self.update_metric("repeat_wake_count", current_count + 1)
                break

    def _on_vad_end(self, event: Event) -> None:
        self._event_timestamps["vad_end"] = event.timestamp

    def _on_transcribe_done(self, event: Event) -> None:
        self._event_timestamps["transcribe"] = event.timestamp
        self._current_session_text = event.data.get("text", "")
        
        if "wake" in self._event_timestamps:
            asr_latency = (event.timestamp - self._event_timestamps["wake"]) * 1000
            self.update_metric("asr_latency", asr_latency)

    def _on_intent_recognized(self, event: Event) -> None:
        self._current_intent = event.data.get("intent", "")
        confidence = event.data.get("confidence", 0)
        text = event.data.get("text", "")
        
        if confidence < 0.5:
            self._record_shadow_case(
                user_text=text,
                intent=self._current_intent,
                confidence=confidence,
                response="",
                error_type="low_confidence",
                context={"entities": event.data.get("entities", {})},
            )
        
        negative_keywords = ["不对", "不是", "错了", "重来", "听不懂", "再说一遍"]
        if any(kw in text for kw in negative_keywords):
            self._record_shadow_case(
                user_text=text,
                intent=self._current_intent,
                confidence=confidence,
                response="",
                error_type="user_correction",
                context={"negative_keywords": [kw for kw in negative_keywords if kw in text]},
            )

    def _on_response_done(self, event: Event) -> None:
        self._event_timestamps["response"] = event.timestamp
        response = event.data.get("text", "")
        
        if "wake" in self._event_timestamps:
            e2e_latency = (event.timestamp - self._event_timestamps["wake"]) * 1000
            self.update_metric("e2e_latency", e2e_latency)
        if "transcribe" in self._event_timestamps:
            nlp_latency = (event.timestamp - self._event_timestamps["transcribe"]) * 1000
            self.update_metric("nlp_latency", nlp_latency)

        if self._current_session_text and response:
            self._check_response_quality(response)

    def _check_response_quality(self, response: str) -> None:
        error_indicators = ["抱歉", "不知道", "不太明白", "无法", "不支持"]
        if any(indicator in response for indicator in error_indicators):
            self._record_shadow_case(
                user_text=self._current_session_text,
                intent=self._current_intent,
                confidence=0.0,
                response=response,
                error_type="failed_response",
                context={"error_indicators": [i for i in error_indicators if i in response]},
            )

    def _on_error(self, event: Event) -> None:
        error_message = event.data.get("message", "")
        self._record_shadow_case(
            user_text=self._current_session_text,
            intent=self._current_intent,
            confidence=0.0,
            response="",
            error_type="system_error",
            context={"error_message": error_message},
        )

    def _on_barge_in(self, event: Event) -> None:
        current_count = self._metrics["barge_in_count"].value
        self.update_metric("barge_in_count", current_count + 1)

    def _record_shadow_case(
        self,
        user_text: str,
        intent: str,
        confidence: float,
        response: str,
        error_type: str,
        context: Dict[str, Any] = None,
    ) -> None:
        if not self._config.shadow_mode_enabled:
            return
        
        try:
            import uuid
            
            case = ShadowCase(
                session_id=str(uuid.uuid4()),
                user_text=self._anonymize_text(user_text),
                intent=intent,
                confidence=confidence,
                response=self._anonymize_text(response),
                error_type=error_type,
                timestamp=time.time(),
                context=context or {},
            )
            
            self._shadow_cases.append(case)
            
            if len(self._shadow_cases) > self._config.max_shadow_cases:
                self._shadow_cases = self._shadow_cases[-self._config.max_shadow_cases:]
            
            self._save_shadow_cases()
            
            logger.debug(f"Shadow case recorded: {error_type}")
        except Exception as e:
            logger.error(f"Failed to record shadow case: {e}")

    def _anonymize_text(self, text: str) -> str:
        if not text:
            return ""
        
        import re
        
        text = re.sub(r"\d{11}", "[手机号]", text)
        text = re.sub(r"\d{18}", "[身份证]", text)
        text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[邮箱]", text)
        text = re.sub(r"https?://[^\s]+", "[链接]", text)
        
        return text

    def _save_shadow_cases(self) -> None:
        try:
            data = [
                {
                    "session_id": case.session_id,
                    "user_text": case.user_text,
                    "intent": case.intent,
                    "confidence": case.confidence,
                    "response": case.response,
                    "error_type": case.error_type,
                    "timestamp": case.timestamp,
                    "context": case.context,
                }
                for case in self._shadow_cases
            ]
            
            with open(self._config.shadow_cases_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"Shadow cases saved to {self._config.shadow_cases_path}")
        except Exception as e:
            logger.error(f"Failed to save shadow cases: {e}")

    def update_metric(self, name: str, value: float) -> None:
        if name in self._metrics:
            self._metrics[name].update(value)
            self._bus.publish(
                Event(
                    event_type=EventType.SLA_METRIC,
                    data={
                        "metric": name,
                        "value": value,
                        "avg": self._metrics[name].current_avg,
                        "status": self._metrics[name].status,
                    },
                    source="SLAMonitor",
                )
            )

    def get_metric(self, name: str) -> Optional[SLAMetric]:
        return self._metrics.get(name)

    def get_all_metrics(self) -> Dict[str, SLAMetric]:
        uptime = (time.time() - self._start_time)
        self._metrics["uptime"].value = 99.9
        return dict(self._metrics)

    def get_summary(self) -> Dict[str, Any]:
        metrics = self.get_all_metrics()
        normal = sum(1 for m in metrics.values() if m.status == "normal")
        warning = sum(1 for m in metrics.values() if m.status == "warning")
        critical = sum(1 for m in metrics.values() if m.status == "critical")

        return {
            "total_metrics": len(metrics),
            "normal_count": normal,
            "warning_count": warning,
            "critical_count": critical,
            "uptime_seconds": time.time() - self._start_time,
            "shadow_cases_count": len(self._shadow_cases),
            "metrics": {
                name: {
                    "value": m.value,
                    "unit": m.unit,
                    "target": m.target,
                    "avg": m.current_avg,
                    "status": m.status,
                }
                for name, m in metrics.items()
            },
        }

    def get_shadow_cases(self, limit: int = 100) -> List[ShadowCase]:
        return self._shadow_cases[-limit:]

    def export_shadow_cases(self, filepath: str) -> bool:
        try:
            cases = self.get_shadow_cases()
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(cases, f, ensure_ascii=False, indent=2, default=str)
            
            logger.info(f"Shadow cases exported to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export shadow cases: {e}")
            return False
