from __future__ import annotations
import time
import threading
import numpy as np
from abc import ABC, abstractmethod
from typing import Optional, Callable
from ..utils.logger import logger
from ..core.message_bus import MessageBus, Event, EventType


class AcousticEchoCanceller(ABC):
    """
    声学回声消除器抽象基类

    预留进阶AEC接口，子类需实现核心回声消除逻辑
    """

    def __init__(self, sample_rate: int, block_size: int = 512) -> None:
        """
        初始化回声消除器

        Args:
            sample_rate: 采样率
            block_size: 处理块大小
        """
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._enabled = False
        logger.info(f"AcousticEchoCanceller initialized: sr={sample_rate}, block={block_size}")

    @abstractmethod
    def process(
        self,
        mic_audio: np.ndarray,
        ref_audio: np.ndarray,
    ) -> np.ndarray:
        """
        执行回声消除

        Args:
            mic_audio: 麦克风采集的音频（包含回声）
            ref_audio: TTS播放的参考信号

        Returns:
            消除回声后的干净音频
        """
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        """重置滤波器状态"""
        raise NotImplementedError

    def enable(self) -> None:
        """启用回声消除"""
        self._enabled = True
        logger.info("AcousticEchoCanceller enabled")

    def disable(self) -> None:
        """禁用回声消除"""
        self._enabled = False
        logger.info("AcousticEchoCanceller disabled")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def block_size(self) -> int:
        return self._block_size


class NLMSAEC(AcousticEchoCanceller):
    """
    NLMS自适应滤波器回声消除器（预留框架）

    基于归一化最小均方算法的回声消除实现
    """

    def __init__(self, sample_rate: int, block_size: int = 512, filter_length: int = 1024) -> None:
        """
        初始化NLMS回声消除器

        Args:
            sample_rate: 采样率
            block_size: 处理块大小
            filter_length: 滤波器长度（决定回声延迟补偿能力）
        """
        super().__init__(sample_rate, block_size)
        self._filter_length = filter_length
        self._weights: np.ndarray = np.zeros(filter_length)
        self._ref_buffer: np.ndarray = np.zeros(filter_length)
        self._mu = 0.1
        self._alpha = 0.95
        logger.info(f"NLMSAEC initialized: filter_length={filter_length}, mu={self._mu}")

    def process(
        self,
        mic_audio: np.ndarray,
        ref_audio: np.ndarray,
    ) -> np.ndarray:
        """
        执行NLMS自适应滤波回声消除

        核心逻辑：
        1. 更新参考信号缓冲
        2. 计算估计回声（滤波器输出）
        3. 计算误差信号（麦克风信号 - 估计回声）
        4. 使用NLMS算法更新滤波器权重
        5. 返回误差信号作为干净音频

        Args:
            mic_audio: 麦克风采集的音频
            ref_audio: TTS播放的参考信号

        Returns:
            消除回声后的音频
        """
        if not self._enabled:
            return mic_audio

        if len(mic_audio) != self._block_size or len(ref_audio) != self._block_size:
            logger.warning(f"Audio block size mismatch: mic={len(mic_audio)}, ref={len(ref_audio)}, expected={self._block_size}")
            return mic_audio

        clean_audio = np.zeros_like(mic_audio)

        for n in range(self._block_size):
            self._ref_buffer = np.roll(self._ref_buffer, 1)
            if n < len(ref_audio):
                self._ref_buffer[0] = ref_audio[n]

            estimated_echo = np.dot(self._weights, self._ref_buffer)

            error = mic_audio[n] - estimated_echo
            clean_audio[n] = error

            x_norm = np.dot(self._ref_buffer, self._ref_buffer)
            step_size = self._mu / (self._alpha + x_norm + 1e-6)
            self._weights = self._weights + step_size * error * self._ref_buffer

        return clean_audio

    def reset(self) -> None:
        """重置滤波器权重和缓冲"""
        self._weights = np.zeros(self._filter_length)
        self._ref_buffer = np.zeros(self._filter_length)
        logger.info("NLMSAEC reset")


class AudioGate:
    """
    麦克风输入门控模块

    通过对话状态控制麦克风音频是否送入ASR识别引擎，解决AI回复时自身声音被录入的问题
    """

    GATE_MODE_PASSTHROUGH = "passthrough"
    GATE_MODE_CONTROLLED = "controlled"

    def __init__(
        self,
        bus: MessageBus,
        sample_rate: int = 16000,
        mode: str = GATE_MODE_CONTROLLED,
        resume_delay_ms: int = 300,
        enable_aec: bool = False,
    ) -> None:
        """
        初始化麦克风门控模块

        Args:
            bus: 消息总线实例
            sample_rate: 采样率
            mode: 门控模式
                - 'passthrough': 直通模式，不进行门控控制
                - 'controlled': 受控模式，根据对话状态控制音频通路
            resume_delay_ms: 从responding状态恢复到idle后延迟开启ASR的时间（毫秒）
            enable_aec: 是否启用回声消除（预留）
        """
        self._bus = bus
        self._sample_rate = sample_rate
        self._mode = mode
        self._resume_delay_ms = resume_delay_ms
        self._enable_aec = enable_aec

        self._is_gate_open = True
        self._current_dialog_state = "idle"
        self._resume_timer: Optional[threading.Timer] = None
        self._sub_id_dialog: Optional[str] = None
        self._sub_id_audio: Optional[str] = None
        self._running = False

        self._aec: Optional[AcousticEchoCanceller] = None
        if self._enable_aec:
            self._aec = NLMSAEC(sample_rate)

        logger.info(
            f"AudioGate initialized: mode={mode}, resume_delay={resume_delay_ms}ms, aec={'ON' if enable_aec else 'OFF'}"
        )

    def start(self) -> None:
        """启动门控模块，订阅相关事件"""
        if self._running:
            return

        self._running = True
        self._subscribe_events()
        logger.info("AudioGate started")

    def stop(self) -> None:
        """停止门控模块，清理资源"""
        if not self._running:
            return

        self._running = False
        self._unsubscribe_events()

        if self._resume_timer:
            self._resume_timer.cancel()
            self._resume_timer = None

        if self._aec:
            self._aec.reset()

        logger.info("AudioGate stopped")

    def _subscribe_events(self) -> None:
        """订阅对话状态变化事件和音频输入事件"""
        self._sub_id_dialog = self._bus.subscribe(
            EventType.DIALOG_STATE_CHANGED,
            self._on_dialog_state_changed,
            "audio_gate",
            priority=1,
        )

        self._sub_id_audio = self._bus.subscribe(
            EventType.PROCESSED_AUDIO,
            self._on_processed_audio,
            "audio_gate",
            priority=3,
        )

    def _unsubscribe_events(self) -> None:
        """取消事件订阅"""
        if self._sub_id_dialog:
            self._bus.unsubscribe(self._sub_id_dialog)
            self._sub_id_dialog = None

        if self._sub_id_audio:
            self._bus.unsubscribe(self._sub_id_audio)
            self._sub_id_audio = None

    def _on_dialog_state_changed(self, event: Event) -> None:
        """
        处理对话状态变化事件

        Args:
            event: DIALOG_STATE_CHANGED事件，包含当前状态
        """
        state = event.data.get("state", "idle")
        if state == self._current_dialog_state:
            return

        old_state = self._current_dialog_state
        self._current_dialog_state = state

        logger.info(f"Dialog state changed: {old_state} -> {state}, gate_open={self._is_gate_open}")

        if self._mode == self.GATE_MODE_PASSTHROUGH:
            return

        if state == "responding":
            self._close_gate()
        elif state == "idle":
            self._schedule_resume()
        elif state == "listening":
            self._open_gate()

    def _on_processed_audio(self, event: Event) -> None:
        """
        处理预处理后的音频事件

        根据门控状态决定是否将音频传递给ASR模块

        Args:
            event: PROCESSED_AUDIO事件
        """
        if self._mode == self.GATE_MODE_PASSTHROUGH:
            return

        if self._is_gate_open:
            audio_data = event.data.get("audio")
            if audio_data is not None and len(audio_data) > 0:
                if self._aec and self._aec.enabled:
                    ref_audio = event.data.get("ref_audio", np.zeros_like(audio_data))
                    audio_data = self._aec.process(audio_data, ref_audio)

                self._bus.publish(
                    Event(
                        event_type=EventType.GATED_AUDIO,
                        data={
                            "audio": audio_data,
                            "sample_rate": event.data.get("sample_rate", self._sample_rate),
                            "timestamp": event.data.get("timestamp", time.time()),
                            "source": "AudioGate",
                        },
                        source="AudioGate",
                        priority=4,
                    )
                )
                logger.debug(f"AudioGate: audio passed through (frames={len(audio_data)})")
        else:
            logger.debug("AudioGate: audio blocked (gate closed)")

    def _close_gate(self) -> None:
        """关闭门控，阻止音频送入ASR"""
        if self._is_gate_open:
            self._is_gate_open = False

            if self._resume_timer:
                self._resume_timer.cancel()
                self._resume_timer = None

            logger.info("AudioGate: gate closed (responding)")

    def _open_gate(self) -> None:
        """打开门控，允许音频送入ASR"""
        if not self._is_gate_open:
            self._is_gate_open = True

            if self._resume_timer:
                self._resume_timer.cancel()
                self._resume_timer = None

            logger.info("AudioGate: gate opened")

    def _schedule_resume(self) -> None:
        """
        延迟开启门控

        在AI回复结束后延迟一段时间再开启ASR，避免尾音回声被录入
        """
        if self._resume_timer:
            self._resume_timer.cancel()

        delay_seconds = self._resume_delay_ms / 1000.0
        logger.info(f"AudioGate: scheduling gate open in {self._resume_delay_ms}ms")

        self._resume_timer = threading.Timer(
            delay_seconds,
            self._open_gate,
        )
        self._resume_timer.daemon = True
        self._resume_timer.start()

    def set_mode(self, mode: str) -> None:
        """
        设置门控模式

        Args:
            mode: 'passthrough' 或 'controlled'
        """
        if mode not in [self.GATE_MODE_PASSTHROUGH, self.GATE_MODE_CONTROLLED]:
            logger.warning(f"Invalid gate mode: {mode}, using 'controlled'")
            mode = self.GATE_MODE_CONTROLLED

        self._mode = mode
        if mode == self.GATE_MODE_PASSTHROUGH:
            self._open_gate()

        logger.info(f"AudioGate mode changed to: {mode}")

    def set_resume_delay(self, delay_ms: int) -> None:
        """
        设置恢复延迟时间

        Args:
            delay_ms: 延迟时间（毫秒）
        """
        self._resume_delay_ms = delay_ms
        logger.info(f"AudioGate resume delay changed to: {delay_ms}ms")

    def enable_aec(self, enabled: bool) -> None:
        """
        启用/禁用回声消除

        Args:
            enabled: 是否启用AEC
        """
        self._enable_aec = enabled
        if self._aec:
            if enabled:
                self._aec.enable()
            else:
                self._aec.disable()

        logger.info(f"AudioGate AEC {'enabled' if enabled else 'disabled'}")

    @property
    def is_gate_open(self) -> bool:
        """门控当前状态"""
        return self._is_gate_open

    @property
    def mode(self) -> str:
        """当前门控模式"""
        return self._mode

    @property
    def current_state(self) -> str:
        """当前对话状态"""
        return self._current_dialog_state