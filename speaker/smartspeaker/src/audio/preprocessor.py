from __future__ import annotations
import time
import numpy as np
from typing import Optional, Dict, Any, Tuple
from ..utils.logger import logger
from ..core.message_bus import MessageBus, Event, EventType


class AudioPreprocessor:
    """
    音频前端预处理模块

    实现三级预处理链路：
    1. 带通滤波：300Hz-8000Hz，过滤低频和高频环境噪音
    2. 噪声抑制(ANS)：基于谱减法的基础降噪，压制背景平稳噪音
    3. VAD语音活动检测：基于能量+过零率判断人声起止，只输出有效语音片段

    订阅原始音频输入事件(AUDIO_INPUT)，处理后发布PROCESSED_AUDIO事件给ASR模块
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        bus: Optional[MessageBus] = None,
        enable_filter: bool = True,
        enable_noise_suppression: bool = True,
        enable_vad: bool = True,
        filter_low_cut: float = 300.0,
        filter_high_cut: float = 8000.0,
        vad_energy_threshold: float = 0.02,
        vad_zcr_threshold: float = 0.05,
        vad_min_speech_frames: int = 3,
        vad_min_silence_frames: int = 10,
        noise_history_size: int = 20,
        noise_decay_factor: float = 0.95,
        noise_calibration_frames: int = 50,
        noise_threshold_multiplier: float = 3.0,
        vad_hysteresis_ratio: float = 0.5,
        min_speech_duration_ms: int = 200,
        energy_gate_threshold: float = 0.002,
    ) -> None:
        """
        初始化音频预处理模块

        Args:
            sample_rate: 采样率，默认16000Hz
            bus: 消息总线实例
            enable_filter: 是否启用带通滤波
            enable_noise_suppression: 是否启用噪声抑制
            enable_vad: 是否启用VAD检测
            filter_low_cut: 带通滤波低频截止频率(Hz)
            filter_high_cut: 带通滤波高频截止频率(Hz)
            vad_energy_threshold: VAD能量阈值（基础值）
            vad_zcr_threshold: VAD过零率阈值
            vad_min_speech_frames: VAD最小语音帧数
            vad_min_silence_frames: VAD最小静音帧数
            noise_history_size: 噪声估计历史帧数
            noise_decay_factor: 噪声估计衰减因子
            noise_calibration_frames: 噪声底标定帧数（启动后采集）
            noise_threshold_multiplier: 动态阈值倍数（能量 > noise_floor * K）
            vad_hysteresis_ratio: 滞回比例（退出阈值 = 进入阈值 * ratio）
            min_speech_duration_ms: 最小语音时长(ms)，过滤短噪点
            energy_gate_threshold: 能量门限，低于此值直接丢弃
        """
        self._sample_rate = sample_rate
        self._bus = bus
        self._enable_filter = enable_filter
        self._enable_noise_suppression = enable_noise_suppression
        self._enable_vad = enable_vad

        self._filter_low_cut = filter_low_cut
        self._filter_high_cut = filter_high_cut

        self._vad_energy_threshold = vad_energy_threshold
        self._vad_zcr_threshold = vad_zcr_threshold
        self._vad_min_speech_frames = vad_min_speech_frames
        self._vad_min_silence_frames = vad_min_silence_frames

        self._noise_history_size = noise_history_size
        self._noise_decay_factor = noise_decay_factor

        self._noise_calibration_frames = noise_calibration_frames
        self._noise_threshold_multiplier = noise_threshold_multiplier
        self._vad_hysteresis_ratio = vad_hysteresis_ratio
        self._min_speech_duration_ms = min_speech_duration_ms
        self._energy_gate_threshold = energy_gate_threshold

        self._noise_floor_rms = 0.0
        self._calibration_frames = 0
        self._calibration_buffer: list[float] = []
        self._is_calibrated = False

        self._vad_enter_threshold = vad_energy_threshold
        self._vad_exit_threshold = vad_energy_threshold * vad_hysteresis_ratio

        self._speech_start_time = 0.0
        self._speech_duration = 0.0

        self._noise_spectrum: Optional[np.ndarray] = None
        self._noise_history: list[np.ndarray] = []

        self._vad_speech_frames = 0
        self._vad_silence_frames = 0
        self._is_in_speech = False
        self._speech_buffer: list[np.ndarray] = []

        self._filter_coeffs: Optional[Tuple[np.ndarray, np.ndarray]] = None
        self._filter_state: Optional[np.ndarray] = None

        self._sub_id: Optional[str] = None
        self._running = False

        if sample_rate > 0:
            self._init_filter_coeffs()

        logger.info(
            f"AudioPreprocessor initialized: sr={sample_rate}, "
            f"filter={'ON' if enable_filter else 'OFF'}, "
            f"ans={'ON' if enable_noise_suppression else 'OFF'}, "
            f"vad={'ON' if enable_vad else 'OFF'}, "
            f"calibration_frames={noise_calibration_frames}, "
            f"noise_multiplier={noise_threshold_multiplier}"
        )

    def _init_filter_coeffs(self) -> None:
        """初始化带通滤波器系数"""
        try:
            from scipy.signal import butter, buttord
            nyquist = self._sample_rate / 2.0

            if self._filter_low_cut > 0:
                low = self._filter_low_cut / nyquist
            else:
                low = 0.0

            if self._filter_high_cut < nyquist:
                high = self._filter_high_cut / nyquist
            else:
                high = 0.99

            if low >= high or low < 0 or high > 1:
                logger.warning(f"Invalid filter parameters: low={low}, high={high}. Using default order=4")
                order = 4
            else:
                try:
                    order, _ = buttord([low, high], [low * 0.8, high * 1.2], 3, 40)
                    order = int(order)
                    if order <= 0:
                        order = 4
                except Exception as e:
                    logger.warning(f"buttord failed: {e}. Using default order=4")
                    order = 4

            b, a = butter(order, [low, high], btype='band')
            self._filter_coeffs = (b, a)
            self._filter_state = np.zeros(max(len(b), len(a)) - 1)
            logger.info(f"Bandpass filter initialized: {self._filter_low_cut}-{self._filter_high_cut}Hz, order={order}")
        except ImportError:
            logger.warning("scipy not available, bandpass filter disabled")
            self._enable_filter = False
        except Exception as e:
            logger.error(f"Failed to initialize filter: {e}")
            self._enable_filter = False

    def _apply_bandpass_filter(self, audio: np.ndarray) -> np.ndarray:
        """
        应用带通滤波器

        Args:
            audio: 输入音频数据

        Returns:
            滤波后的音频数据
        """
        if not self._enable_filter or self._filter_coeffs is None:
            return audio

        try:
            from scipy.signal import lfilter
            b, a = self._filter_coeffs
            filtered, self._filter_state = lfilter(b, a, audio, zi=self._filter_state)
            return filtered.astype(np.float32)
        except Exception as e:
            logger.error(f"Bandpass filter error: {e}")
            return audio

    def _estimate_noise(self, spectrum: np.ndarray) -> np.ndarray:
        """
        估计噪声谱

        Args:
            spectrum: 当前帧的频谱

        Returns:
            估计的噪声谱
        """
        self._noise_history.append(spectrum)
        if len(self._noise_history) > self._noise_history_size:
            self._noise_history.pop(0)

        if self._noise_spectrum is None:
            self._noise_spectrum = np.copy(spectrum)
        else:
            self._noise_spectrum = (
                self._noise_decay_factor * self._noise_spectrum
                + (1 - self._noise_decay_factor) * np.minimum(self._noise_spectrum, spectrum)
            )

        return self._noise_spectrum

    def _apply_spectral_subtraction(self, audio: np.ndarray) -> np.ndarray:
        """
        应用谱减法降噪

        Args:
            audio: 输入音频数据

        Returns:
            降噪后的音频数据
        """
        if not self._enable_noise_suppression:
            return audio

        if len(audio) < 256:
            return audio

        try:
            n_fft = 512
            hop_length = n_fft // 4
            window = np.hanning(n_fft)

            num_frames = 1 + (len(audio) - n_fft) // hop_length
            if num_frames <= 0:
                return audio

            result = np.zeros(len(audio), dtype=np.float32)

            for i in range(num_frames):
                start = i * hop_length
                end = start + n_fft

                frame = audio[start:end] * window

                spectrum = np.fft.rfft(frame)
                magnitude = np.abs(spectrum)
                phase = np.angle(spectrum)

                noise_magnitude = self._estimate_noise(magnitude)

                subtracted = np.maximum(magnitude - noise_magnitude * 0.8, magnitude * 0.1)

                enhanced = subtracted * np.exp(1j * phase)

                ifft_result = np.fft.irfft(enhanced)

                result[start:end] += ifft_result * window

            max_val = np.max(np.abs(result))
            if max_val > 0:
                result = result / max_val * 0.9

            return result.astype(np.float32)

        except Exception as e:
            logger.error(f"Spectral subtraction error: {e}")
            return audio

    def _compute_energy(self, audio: np.ndarray) -> float:
        """
        计算音频能量

        Args:
            audio: 输入音频数据

        Returns:
            归一化能量值
        """
        if len(audio) == 0:
            return 0.0
        return np.sqrt(np.mean(audio ** 2))

    def _compute_zcr(self, audio: np.ndarray) -> float:
        """
        计算过零率

        Args:
            audio: 输入音频数据

        Returns:
            归一化过零率
        """
        if len(audio) == 0:
            return 0.0
        return np.mean(np.abs(np.diff(np.sign(audio)))) / 2.0

    def _calibrate_noise_floor(self, energy: float) -> None:
        """
        噪声底标定：在启动后采集一定帧数的能量，计算噪声底

        Args:
            energy: 当前帧的能量值
        """
        if self._is_calibrated:
            return

        self._calibration_buffer.append(energy)
        self._calibration_frames += 1

        if self._calibration_frames >= self._noise_calibration_frames:
            self._noise_floor_rms = np.median(self._calibration_buffer)
            self._vad_enter_threshold = max(
                self._vad_energy_threshold,
                self._noise_floor_rms * self._noise_threshold_multiplier
            )
            self._vad_exit_threshold = self._vad_enter_threshold * self._vad_hysteresis_ratio
            self._is_calibrated = True
            logger.info(
                f"Noise floor calibrated: rms={self._noise_floor_rms:.6f}, "
                f"enter_threshold={self._vad_enter_threshold:.6f}, "
                f"exit_threshold={self._vad_exit_threshold:.6f}"
            )

    def _vad_detect(self, audio: np.ndarray) -> Tuple[bool, bool]:
        """
        VAD语音活动检测（增强版）

        改进点：
        1. 动态噪声底估计：启动后自动标定环境噪声
        2. 滞回机制：进入语音态用高阈值，退出用低阈值，避免抖动
        3. 能量门控：极低能量帧直接判定为静音

        Args:
            audio: 输入音频数据

        Returns:
            Tuple[is_speech, speech_started]
                is_speech: 当前帧是否为语音
                speech_started: 是否刚进入语音状态
        """
        if not self._enable_vad:
            return True, False

        energy = self._compute_energy(audio)
        zcr = self._compute_zcr(audio)

        if energy < self._energy_gate_threshold:
            if self._is_in_speech:
                self._vad_silence_frames += 1
                if self._vad_silence_frames >= self._vad_min_silence_frames:
                    self._is_in_speech = False
                    logger.debug(f"VAD: speech ended (energy gate, silence={self._vad_silence_frames})")
            else:
                self._vad_silence_frames = 0
            return False, False

        if not self._is_in_speech:
            self._calibrate_noise_floor(energy)

        if self._is_calibrated:
            enter_threshold = self._vad_enter_threshold
            exit_threshold = self._vad_exit_threshold
        else:
            enter_threshold = self._vad_energy_threshold
            exit_threshold = self._vad_energy_threshold * self._vad_hysteresis_ratio

        is_speech_frame = (
            energy > enter_threshold
            and zcr > self._vad_zcr_threshold
        )

        speech_started = False

        if is_speech_frame:
            self._vad_speech_frames += 1
            self._vad_silence_frames = 0

            if not self._is_in_speech and self._vad_speech_frames >= self._vad_min_speech_frames:
                self._is_in_speech = True
                speech_started = True
                self._speech_start_time = time.time()
                logger.debug(
                    f"VAD: speech started (energy={energy:.4f}, zcr={zcr:.4f}, "
                    f"threshold={enter_threshold:.4f})"
                )
        else:
            if self._is_in_speech:
                if energy > exit_threshold:
                    self._vad_silence_frames = 0
                else:
                    self._vad_silence_frames += 1
                    if self._vad_silence_frames >= self._vad_min_silence_frames:
                        self._is_in_speech = False
                        self._speech_duration = (time.time() - self._speech_start_time) * 1000
                        logger.debug(
                            f"VAD: speech ended (silence={self._vad_silence_frames}, "
                            f"duration={self._speech_duration:.1f}ms)"
                        )
            else:
                self._vad_speech_frames = max(0, self._vad_speech_frames - 1)
                self._vad_silence_frames = 0

        return self._is_in_speech, speech_started

    def process(self, audio: np.ndarray) -> Tuple[Optional[np.ndarray], bool]:
        """
        执行完整的音频预处理链路

        Args:
            audio: 原始音频数据

        Returns:
            Tuple[processed_audio, is_speech]
                processed_audio: 处理后的音频数据，无人声时返回None
                is_speech: 当前是否检测到语音
        """
        if len(audio) == 0:
            return None, False

        filtered = self._apply_bandpass_filter(audio)

        denoised = self._apply_spectral_subtraction(filtered)

        is_speech, _ = self._vad_detect(denoised)

        if is_speech:
            self._speech_buffer.append(denoised)
            return denoised, True
        else:
            if self._speech_buffer:
                full_audio = np.concatenate(self._speech_buffer)
                self._speech_buffer = []

                speech_duration_ms = (len(full_audio) / self._sample_rate) * 1000
                if speech_duration_ms < self._min_speech_duration_ms:
                    logger.debug(
                        f"VAD: speech too short ({speech_duration_ms:.1f}ms), "
                        f"discarded (min={self._min_speech_duration_ms}ms)"
                    )
                    return None, False

                logger.debug(f"VAD: speech ended, duration={speech_duration_ms:.1f}ms")
                return full_audio, True
            return None, False

    def flush(self) -> Optional[np.ndarray]:
        """
        刷新缓冲区，返回剩余的语音数据

        Returns:
            剩余的语音数据，无数据时返回None
        """
        if self._speech_buffer:
            full_audio = np.concatenate(self._speech_buffer)
            self._speech_buffer = []
            return full_audio
        return None

    def reset(self) -> None:
        """重置所有状态"""
        self._noise_spectrum = None
        self._noise_history = []
        self._vad_speech_frames = 0
        self._vad_silence_frames = 0
        self._is_in_speech = False
        self._speech_buffer = []
        if self._filter_state is not None:
            self._filter_state[:] = 0.0
        self._noise_floor_rms = 0.0
        self._calibration_frames = 0
        self._calibration_buffer = []
        self._is_calibrated = False
        self._speech_start_time = 0.0
        self._speech_duration = 0.0

    def _on_audio_input(self, event: Event) -> None:
        """
        处理原始音频输入事件

        Args:
            event: AUDIO_INPUT事件
        """
        audio_data = event.data.get("audio", event.data.get("samples"))
        if audio_data is None:
            return

        if isinstance(audio_data, list):
            audio_data = np.array(audio_data, dtype=np.float32)
        elif not isinstance(audio_data, np.ndarray):
            return

        processed_audio, is_speech = self.process(audio_data)

        if processed_audio is not None and len(processed_audio) > 0:
            self._bus.publish(
                Event(
                    event_type=EventType.PROCESSED_AUDIO,
                    data={
                        "audio": processed_audio,
                        "sample_rate": self._sample_rate,
                        "is_speech": is_speech,
                        "timestamp": event.data.get("timestamp", time.time()),
                    },
                    source="AudioPreprocessor",
                    priority=4,
                )
            )

    def start(self) -> None:
        """启动预处理模块，订阅音频输入事件"""
        if self._running:
            return

        if self._bus is not None:
            self._sub_id = self._bus.subscribe(
                EventType.AUDIO_INPUT,
                self._on_audio_input,
                "audio_preprocessor",
                priority=4,
            )

        self._running = True
        logger.info("AudioPreprocessor started")

    def stop(self) -> None:
        """停止预处理模块，取消订阅"""
        if not self._running:
            return

        if self._sub_id is not None:
            self._bus.unsubscribe(self._sub_id)
            self._sub_id = None

        self.reset()
        self._running = False
        logger.info("AudioPreprocessor stopped")

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running

    @property
    def config(self) -> Dict[str, Any]:
        """获取当前配置参数"""
        return {
            "sample_rate": self._sample_rate,
            "enable_filter": self._enable_filter,
            "enable_noise_suppression": self._enable_noise_suppression,
            "enable_vad": self._enable_vad,
            "filter_low_cut": self._filter_low_cut,
            "filter_high_cut": self._filter_high_cut,
            "vad_energy_threshold": self._vad_energy_threshold,
            "vad_zcr_threshold": self._vad_zcr_threshold,
            "vad_min_speech_frames": self._vad_min_speech_frames,
            "vad_min_silence_frames": self._vad_min_silence_frames,
            "noise_history_size": self._noise_history_size,
            "noise_decay_factor": self._noise_decay_factor,
        }