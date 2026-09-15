from __future__ import annotations
import os
import time
import sys
import traceback
import threading
import numpy as np
from typing import Optional, List
from ..utils.logger import logger

from ..core.message_bus import MessageBus, Event, EventType
from ..core.strategy import StrategyManager
from ..config import AudioConfig
from .strategies import (
    WakeWordStrategy,
    VADStrategy,
    ASRStrategy,
    MockWakeWord,
    MockVAD,
    MockASR,
    WhisperASR,
    WebRTCVAD,
    PorcupineWakeWord,
    SherpaOnnxASR,
    FasterWhisperASR,
    ParaformerASR,
)
from .tts import TTSStrategy, MockTTS, Pyttsx3TTS, EdgeTTSTTS, AutoTTS, EspeakNGTTS, SherpaOnnxTTS
from .player import AudioPlayer
from .device_finder import find_audio_device, list_audio_devices, find_input_device_by_keyword, find_output_device_by_keyword
from .aec import AECProcessor, BargeInDetector
from .music_player import MusicPlayer


class AudioProcessor:
    def __init__(self, config: AudioConfig, bus: MessageBus, music_dir: Optional[str] = None) -> None:
        self._config = config
        self._bus = bus
        self._running = False
        self._stream = None
        self._audio_buffer: list[np.ndarray] = []
        self._audio_buffer_lock = threading.Lock()
        self._speech_buffer = []
        self._is_recording = False
        self._wake_detected = False
        self._sd_module = None
        self._recording_enabled = False
        self._is_playing = False
        self._playback_buffer = []
        self._silence_frame_count = 0
        self._state_lock = threading.RLock()
        # 预缓冲：保留唤醒前的最近 N 帧音频，避免唤醒后开头丢字
        self._pre_buffer: list[np.ndarray] = []
        self._pre_buffer_max_frames = 15  # ~15帧 × 64ms ≈ 1秒预缓冲
        # 录音开始时间戳，用于最大录音时长保护
        self._recording_start_time: float = 0.0
        # 标记是否已收到真实语音内容，避免唤醒后初始静音触发结束
        self._has_speech_content: bool = False
        # TTS 播放结束时间戳，用于唤醒词冷却（防止 TTS 尾音触发误唤醒）
        self._last_tts_end_time: float = 0.0

        self._input_device_idx = self._resolve_device(config.input_device, config.input_device_name, "input")
        self._output_device_idx = self._resolve_device(config.output_device, config.output_device_name, "output")

        logger.info(f"Input device index: {self._input_device_idx}, config.input_device: {config.input_device}, config.input_device_name: {config.input_device_name}")
        logger.info(f"Output device index: {self._output_device_idx}, config.output_device: {config.output_device}, config.output_device_name: {config.output_device_name}")

        self._wakeword_manager = StrategyManager()
        self._vad_manager = StrategyManager()
        self._asr_manager = StrategyManager()
        self._tts_manager = StrategyManager()
        self._player = AudioPlayer(config.sample_rate, self._output_device_idx)
        
        resolved_music_dir = music_dir if music_dir else self._find_music_dir()
        self._music_player = MusicPlayer(
            output_device=self._output_device_idx,
            bus=self._bus,
            music_dir=resolved_music_dir,
        )
        
        self._aec_processor = AECProcessor(config.sample_rate)
        self._barge_in_detector = BargeInDetector(config.sample_rate, config.barge_in_threshold)
        self._preprocessor_enabled = getattr(config, 'preprocessor_enabled', False)
        self._gate_enabled = getattr(config, 'gate_enabled', False)
        
        self._playback_buffer_lock = threading.Lock()

        self._setup_strategies()
        self._subscribe_events()

        logger.info("AudioProcessor initialized")

    def _try_load_asr_model(self, asr_strategy, timeout: float = 10.0) -> bool:
        """带超时保护的ASR模型加载，防止加载过程卡死"""
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asr_strategy.load_model)
                try:
                    result = future.result(timeout=timeout)
                    return result
                except concurrent.futures.TimeoutError:
                    logger.warning(f"ASR model loading timed out after {timeout}s: {asr_strategy.name}")
                    return False
        except Exception as e:
            logger.warning(f"ASR model loading error: {e}")
            return False

    def _resolve_device(self, device_idx: Optional[int], device_name: Optional[str], device_type: str) -> Optional[int]:
        logger.info(f"_resolve_device called: device_idx={device_idx}, device_name={device_name}, device_type={device_type}")

        if device_idx is not None:
            logger.info(f"Using direct device index: {device_idx}")
            return device_idx

        if device_name:
            idx = find_audio_device(device_name, device_type)
            if idx is not None:
                logger.info(f"Found {device_type} device '{device_name}' at index {idx}")
                return idx

            logger.info(f"Device name '{device_name}' not found, trying keyword match...")
            if device_type == "input":
                idx = find_input_device_by_keyword()
            else:
                idx = find_output_device_by_keyword()
            if idx is not None:
                logger.info(f"Found {device_type} device via keyword match at index {idx}")
                return idx

        logger.info(f"No device specified, trying keyword match...")
        if device_type == "input":
            idx = find_input_device_by_keyword()
        else:
            idx = find_output_device_by_keyword()
        if idx is not None:
            logger.info(f"Found {device_type} device via keyword match at index {idx}")
            return idx

        logger.warning(f"No device specified for {device_type}, returning None")
        return None

    def _find_music_dir(self) -> str:
        """查找音乐目录：依次尝试多个可能的位置"""
        # 候选路径列表
        candidates = []

        # 0. 环境变量 / 配置指定的路径（最高优先级）
        if getattr(self._config, 'music_dir', None):
            candidates.append(self._config.music_dir)

        # 1. 项目根目录的 data/music（smart-speaker/data/music）
        candidates.append(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "music"))
        )
        # 2. smart-speaker-src/data/music
        candidates.append(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "music"))
        )

        for path in candidates:
            if path and os.path.isdir(path):
                logger.info(f"Music directory found: {path}")
                return path

        # 未找到则返回默认路径（会自动创建）
        default = candidates[-1]
        logger.info(f"Music directory not found, using default: {default}")
        return default

    def _setup_strategies(self) -> None:
        mock_wake = MockWakeWord(self._config.wake_word)
        self._wakeword_manager.register(mock_wake)

        porcupine_wake = PorcupineWakeWord(
            access_key=self._config.porcupine_access_key,
            wake_word=self._config.wake_word,
        )
        self._wakeword_manager.register(porcupine_wake)

        if self._config.porcupine_access_key:
            self._wakeword_manager.set_current(porcupine_wake.name)
        else:
            self._wakeword_manager.set_current(mock_wake.name)

        mock_vad = MockVAD(self._config.silence_threshold)
        self._vad_manager.register(mock_vad)

        webrtc_vad = WebRTCVAD(
            mode=self._config.vad_mode,
            sample_rate=self._config.sample_rate,
            min_energy=self._config.vad_energy_threshold,
            energy_multiplier=self._config.vad_energy_multiplier,
            min_speech_frames=self._config.vad_min_speech_frames,
        )
        self._vad_manager.register(webrtc_vad)
        self._vad_manager.set_current(webrtc_vad.name)

        mock_asr = MockASR()
        self._asr_manager.register(mock_asr)

        whisper_asr = WhisperASR("base")
        self._asr_manager.register(whisper_asr)

        faster_whisper_asr = FasterWhisperASR(self._config.faster_whisper_model)
        self._asr_manager.register(faster_whisper_asr)

        sherpa_asr_model = getattr(self._config, 'sherpa_asr_model', None) or ""
        sherpa_asr_type = getattr(self._config, 'sherpa_asr_type', 'paraformer') or "paraformer"
        asr_auto_download = getattr(self._config, 'asr_auto_download', False)
        sherpa_asr = SherpaOnnxASR(model_dir=sherpa_asr_model, model_type=sherpa_asr_type, auto_download=asr_auto_download)
        self._asr_manager.register(sherpa_asr)

        paraformer_asr = ParaformerASR(model_dir=sherpa_asr_model)
        self._asr_manager.register(paraformer_asr)

        asr_engine = getattr(self._config, 'asr_engine', 'sherpa_onnx').lower()

        if asr_engine == "mock":
            self._asr_manager.set_current(mock_asr.name)
            logger.info(f"ASR engine: {mock_asr.name} (mock mode)")
        elif asr_engine == "sherpa_onnx":
            if self._try_load_asr_model(sherpa_asr):
                self._asr_manager.set_current(sherpa_asr.name)
                logger.info(f"ASR engine: {sherpa_asr.name}")
            elif self._try_load_asr_model(paraformer_asr):
                self._asr_manager.set_current(paraformer_asr.name)
                logger.info(f"ASR engine: {paraformer_asr.name} (sherpa-onnx failed, fallback to paraformer onnx)")
            else:
                self._asr_manager.set_current(mock_asr.name)
                logger.warning(f"ASR engine: {mock_asr.name} (sherpa-onnx and paraformer both failed, using mock)")
        elif asr_engine == "faster_whisper":
            if self._try_load_asr_model(faster_whisper_asr):
                self._asr_manager.set_current(faster_whisper_asr.name)
                logger.info(f"ASR engine: {faster_whisper_asr.name}")
            else:
                self._asr_manager.set_current(mock_asr.name)
                logger.warning(f"ASR engine: {mock_asr.name} (faster-whisper failed, using mock)")
        elif asr_engine == "whisper":
            if self._try_load_asr_model(whisper_asr):
                self._asr_manager.set_current(whisper_asr.name)
                logger.info(f"ASR engine: {whisper_asr.name}")
            else:
                self._asr_manager.set_current(mock_asr.name)
                logger.warning(f"ASR engine: {mock_asr.name} (whisper failed, using mock)")
        else:
            self._asr_manager.set_current(mock_asr.name)
            logger.info(f"ASR engine: {mock_asr.name} (unknown engine: {asr_engine})")

        mock_tts = MockTTS()
        self._tts_manager.register(mock_tts)

        pyttsx3_tts = Pyttsx3TTS()
        self._tts_manager.register(pyttsx3_tts)

        edge_tts = EdgeTTSTTS(
            voice=self._config.tts_voice,
            rate=self._config.tts_rate,
            volume=self._config.tts_volume,
        )
        self._tts_manager.register(edge_tts)

        espeak_ng_tts = EspeakNGTTS()
        self._tts_manager.register(espeak_ng_tts)

        sherpa_tts = SherpaOnnxTTS(model_path=self._config.sherpa_onnx_model)
        self._tts_manager.register(sherpa_tts)

        auto_tts = AutoTTS(
            voice=self._config.tts_voice,
            rate=self._config.tts_rate,
            volume=self._config.tts_volume,
            sherpa_model=self._config.sherpa_onnx_model,
            gender=self._config.tts_voice_gender,
        )
        self._tts_manager.register(auto_tts)

        engine_pref = self._config.tts_engine.lower()
        if engine_pref == "auto":
            self._tts_manager.set_current("auto_tts")
        elif engine_pref == "edge":
            self._tts_manager.set_current("edge_tts")
        elif engine_pref == "pyttsx3":
            self._tts_manager.set_current("pyttsx3_tts")
        elif engine_pref == "sherpa_onnx":
            self._tts_manager.set_current("sherpa_onnx_tts")
        elif engine_pref == "espeak":
            self._tts_manager.set_current("espeak_ng_tts")
        else:
            self._tts_manager.set_current("auto_tts")

    def _subscribe_events(self) -> None:
        self._bus.subscribe(
            EventType.SYSTEM_STATUS, self._on_system_status, "audio_processor"
        )
        self._bus.subscribe(
            EventType.AUDIO_OUTPUT,
            self._on_audio_output,
            "audio_processor",
        )
        self._bus.subscribe(
            EventType.AUDIO_INTERRUPT,
            self._on_audio_interrupt,
            "audio_processor",
            priority=1,
        )
        if self._gate_enabled:
            self._bus.subscribe(
                EventType.GATED_AUDIO,
                self._on_gated_audio,
                "audio_processor",
            )
        elif self._preprocessor_enabled:
            self._bus.subscribe(
                EventType.PROCESSED_AUDIO,
                self._on_processed_audio,
                "audio_processor",
            )

    def _on_gated_audio(self, event: Event) -> None:
        audio_data = event.data.get("audio", None)
        if audio_data is not None and len(audio_data) > 0:
            self.processAudio(audio_data, bypass_preprocessor=True)

    def _on_processed_audio(self, event: Event) -> None:
        audio_data = event.data.get("audio", None)
        is_speech = event.data.get("is_speech", False)
        
        if audio_data is not None and is_speech:
            self.processAudio(audio_data, bypass_preprocessor=True)

    def _on_system_status(self, event: Event) -> None:
        status = event.data.get("status")
        if status == "shutdown":
            self.stop()

    def _on_audio_interrupt(self, event: Event) -> None:
        reason = event.data.get("reason", "unknown")
        logger.info(f"Audio interrupt received: {reason}")
        
        self._player.stop()
        self._is_playing = False
        with self._playback_buffer_lock:
            self._playback_buffer = []
        
        if hasattr(self, '_stream_playback_queue'):
            with getattr(self, '_stream_playback_lock', threading.Lock()):
                self._stream_playback_queue = []
        
        self._wake_detected = False
        self._is_recording = False
        self._speech_buffer = []
        self._silence_frame_count = 0

    def _on_audio_output(self, event: Event) -> None:
        text = event.data.get("text", "")
        stream_chunk = event.data.get("stream_chunk", False)

        # 空文本不处理，避免空白内容触发 TTS
        if not text or not text.strip():
            return

        if stream_chunk:
            self.speak_stream_chunk(text)
        else:
            self.speak(text)

    def speak(self, text: str, timeout: float = 15.0) -> None:
        """合成并播放TTS语音，带超时保护防止卡死。
        整个合成+播放流程在守护线程中执行，避免阻塞MessageBus。"""
        def _do_speak():
            try:
                logger.info(f"[TTS] 开始播放语音: {text[:40]}...")

                current_strategy_name = self._tts_manager.current
                tts_strategy = self._tts_manager._strategies.get(current_strategy_name)

                if not tts_strategy:
                    logger.warning("[TTS] 未选择TTS策略")
                    return

                audio_data = tts_strategy.synthesize(text)
                sample_rate = tts_strategy.get_sample_rate()

                if len(audio_data) == 0:
                    logger.warning("[TTS] TTS返回空音频数据")
                    return

                audio_data = audio_data.astype(np.float32)

                self._is_playing = True
                with self._playback_buffer_lock:
                    self._playback_buffer = list(audio_data)

                playback_done = threading.Event()
                playback_error = [None]

                def _do_play():
                    try:
                        self._player.play(audio_data, sample_rate)
                    except Exception as e:
                        playback_error[0] = e
                    finally:
                        playback_done.set()

                play_thread = threading.Thread(target=_do_play, daemon=True)
                play_thread.start()

                if not playback_done.wait(timeout=timeout):
                    logger.error(f"TTS playback timed out after {timeout}s, forcing stop")
                    self._player.stop()
                    play_thread.join(timeout=2.0)

                if playback_error[0]:
                    raise playback_error[0]

                self._is_playing = False
                self._last_tts_end_time = time.time()
                with self._playback_buffer_lock:
                    self._playback_buffer = []

                logger.info(f"TTS played: {text[:30]}... ({len(audio_data)} samples at {sample_rate}Hz)")
            except Exception as e:
                logger.error(f"TTS play error: {e}")
                logger.error(f"TTS 完整异常:\n{traceback.format_exc()}")
                self._is_playing = False
                self._last_tts_end_time = time.time()
                with self._playback_buffer_lock:
                    self._playback_buffer = []
            finally:
                # 播放完成（无论成功或失败）后发布 AUDIO_OUTPUT_COMPLETE，
                # 让 DialogManager 能够重置状态为 IDLE，避免状态机卡死在 RESPONDING
                self._bus.publish(
                    Event(
                        event_type=EventType.AUDIO_OUTPUT_COMPLETE,
                        data={"text": text},
                        source="AudioProcessor",
                    )
                )

        threading.Thread(target=_do_speak, daemon=True).start()

    def speak_stream_chunk(self, text: str, timeout: float = 10.0) -> None:
        """流式播放TTS语音片段，支持并行预加载"""
        if not hasattr(self, '_stream_playback_queue'):
            self._stream_playback_queue = []
            self._stream_playback_lock = threading.Lock()
            self._stream_playback_active = threading.Event()
            self._stream_playback_thread = None

        try:
            logger.debug(f"[TTS Stream] 处理流式片段: {text[:30]}...")
            
            current_strategy_name = self._tts_manager.current
            tts_strategy = self._tts_manager._strategies.get(current_strategy_name)

            if not tts_strategy:
                logger.warning("[TTS Stream] 未选择TTS策略")
                return

            audio_data = tts_strategy.synthesize(text)
            sample_rate = tts_strategy.get_sample_rate()

            if len(audio_data) == 0:
                logger.warning("[TTS Stream] TTS返回空音频数据")
                return

            audio_data = audio_data.astype(np.float32)

            with self._stream_playback_lock:
                self._stream_playback_queue.append((audio_data, sample_rate))

            self._start_stream_playback()

        except Exception as e:
            logger.error(f"TTS stream chunk error: {e}")

    def _start_stream_playback(self):
        if self._stream_playback_active.is_set():
            return

        self._stream_playback_active.set()

        def playback_loop():
            while True:
                chunk = None
                with self._stream_playback_lock:
                    if self._stream_playback_queue:
                        chunk = self._stream_playback_queue.pop(0)
                    else:
                        break

                if chunk:
                    audio_data, sample_rate = chunk
                    try:
                        self._is_playing = True
                        self._player.play(audio_data, sample_rate)
                    except Exception as e:
                        logger.error(f"Stream playback error: {e}")
                    finally:
                        self._is_playing = False
                        self._last_tts_end_time = time.time()

            self._stream_playback_active.clear()
            # 宽限期：等待短暂时间看是否有新的流式片段到达，避免在片段之间过早触发完成事件
            time.sleep(0.5)
            # 仅在没有新播放启动且队列仍为空时，才发布完成事件
            if not self._stream_playback_active.is_set():
                with self._stream_playback_lock:
                    queue_empty = not self._stream_playback_queue
                if queue_empty:
                    self._bus.publish(
                        Event(
                            event_type=EventType.AUDIO_OUTPUT_COMPLETE,
                            data={"source": "stream_tts"},
                            source="AudioProcessor",
                        )
                    )

        self._stream_playback_thread = threading.Thread(target=playback_loop, daemon=True)
        self._stream_playback_thread.start()

    def processAudio(self, audio_data: np.ndarray, bypass_preprocessor: bool = False) -> None:
        if not bypass_preprocessor:
            self._bus.publish(
                Event(
                    event_type=EventType.AUDIO_INPUT,
                    data={"samples": len(audio_data), "timestamp": time.time()},
                    source="AudioProcessor",
                )
            )

        if not bypass_preprocessor and self._config.aec_enabled and self._is_playing:
            ref_data = None
            with self._playback_buffer_lock:
                if self._playback_buffer:
                    ref_len = min(len(audio_data), len(self._playback_buffer))
                    ref_data = np.array(self._playback_buffer[:ref_len], dtype=np.float32)
                    self._playback_buffer = self._playback_buffer[ref_len:]

            audio_data = self._aec_processor.process(audio_data, ref_data)

        if not bypass_preprocessor and self._config.barge_in_enabled and self._is_playing:
            if self._barge_in_detector.detect(audio_data):
                self._player.stop()
                self._is_playing = False
                with self._playback_buffer_lock:
                    self._playback_buffer = []
                self._wake_detected = False
                self._is_recording = False
                self._speech_buffer = []
                self._silence_frame_count = 0
                self._bus.publish(
                    Event(
                        event_type=EventType.AUDIO_BARGE_IN,
                        data={"timestamp": time.time()},
                        source="AudioProcessor",
                        priority=4,
                    )
                )
                logger.info("Barge-in detected, stopping playback")
            return

        if self._is_playing:
            return

        # 流式 TTS 播放期间也跳过（chunk 间隙期间 _is_playing 可能短暂为 False）
        if hasattr(self, '_stream_playback_active') and self._stream_playback_active.is_set():
            return

        # TTS 播放结束后的冷却期（2.0秒），防止尾音触发误唤醒
        if self._last_tts_end_time > 0:
            elapsed = time.time() - self._last_tts_end_time
            if elapsed < 2.0:
                return
            self._last_tts_end_time = 0.0

        # 维护预缓冲：始终保留最近N帧，唤醒后拼接到录音开头
        if not self._wake_detected and not self._is_recording:
            self._pre_buffer.append(audio_data)
            if len(self._pre_buffer) > self._pre_buffer_max_frames:
                self._pre_buffer.pop(0)

        if not self._wake_detected:
            detected, confidence = self.detectWakeWord(audio_data)
            if detected:
                logger.info("[唤醒] 检测到唤醒词，开始监听...")
                self._wake_detected = True
                self._is_recording = False
                # 将预缓冲拼接到语音缓冲开头，避免丢失唤醒后的前几个字
                self._speech_buffer = list(self._pre_buffer)
                self._speech_buffer.append(audio_data)  # 当前帧也加入
                self._pre_buffer = []
                self._silence_frame_count = 0
                self._is_recording = True  # 唤醒后立即开始录音，不等VAD
                self._recording_start_time = time.time()
                self._bus.publish(
                    Event(
                        event_type=EventType.WAKE_WORD_DETECTED,
                        data={"confidence": confidence, "timestamp": time.time()},
                        source="AudioProcessor",
                    )
                )
                self._bus.publish(
                    Event(
                        event_type=EventType.VAD_START,
                        data={"timestamp": time.time()},
                        source="AudioProcessor",
                    )
                )
                logger.info(f"[唤醒] 唤醒词检测完成，置信度={confidence:.2f}，预缓冲={len(self._speech_buffer)}帧")
            return

        # 唤醒后：持续收集音频，用VAD判断是否有人声
        is_speech = self.vadSegment(audio_data)

        if is_speech:
            if not self._is_recording:
                logger.info("[VAD] 检测到语音，开始录音...")
                self._is_recording = True
                # 保留之前的缓冲（可能包含语音开头）
                self._speech_buffer.append(audio_data)
                self._silence_frame_count = 0
                self._recording_start_time = time.time()
                self._bus.publish(
                    Event(
                        event_type=EventType.VAD_START,
                        data={"timestamp": time.time()},
                        source="AudioProcessor",
                    )
                )
            else:
                self._speech_buffer.append(audio_data)
                self._silence_frame_count = 0
                self._has_speech_content = True  # 标记已收到真实语音
        else:
            if self._is_recording:
                # 静音帧也加入缓冲（避免截断词尾）
                self._speech_buffer.append(audio_data)
                self._silence_frame_count += 1
                frame_duration = len(audio_data) / self._config.sample_rate
                silence_duration = self._silence_frame_count * frame_duration

                # 最大录音时长保护
                recording_duration = time.time() - self._recording_start_time
                max_duration = getattr(self._config, 'max_speech_duration', 30.0)
                if recording_duration > max_duration:
                    logger.info(f"[VAD] 录音达到最大时长({max_duration:.0f}s)，强制结束")
                    self._finalize_recording()
                    return

                # 只有在已收到真实语音内容后，才允许静音触发结束
                # 避免唤醒后初始静音被误判为"说完了"
                if self._has_speech_content and silence_duration > self._config.min_silence_duration:
                    logger.info(f"[VAD] 检测到静音({silence_duration:.2f}s)，停止录音...")
                    self._finalize_recording()
            else:
                # 唤醒后但尚未检测到语音，继续等待（带超时保护）
                self._silence_frame_count += 1
                frame_duration = len(audio_data) / self._config.sample_rate
                wait_duration = self._silence_frame_count * frame_duration
                # 唤醒后等5秒还没有语音输入，自动放弃本次唤醒
                if wait_duration > 5.0:
                    logger.info("[VAD] 唤醒后5秒内未检测到语音，取消本次唤醒")
                    self._wake_detected = False
                    self._is_recording = False
                    self._speech_buffer = []
                    self._silence_frame_count = 0

    def _finalize_recording(self) -> None:
        """结束录音，执行ASR识别并发布结果"""
        self._is_recording = False
        self._wake_detected = False
        self._silence_frame_count = 0
        self._has_speech_content = False

        if not self._speech_buffer:
            return

        full_audio = np.concatenate(self._speech_buffer)
        self._speech_buffer = []
        speech_duration = len(full_audio) / self._config.sample_rate

        min_speech_duration = getattr(self._config, 'min_speech_duration', 0.5)
        if speech_duration < min_speech_duration:
            logger.debug(f"Speech too short ({speech_duration:.2f}s), ignoring")
            return

        trimmed_audio = self._trim_trailing_silence(full_audio)
        trimmed_duration = len(trimmed_audio) / self._config.sample_rate

        self._bus.publish(
            Event(
                event_type=EventType.VAD_END,
                data={
                    "duration": trimmed_duration,
                    "samples": len(trimmed_audio),
                },
                source="AudioProcessor",
            )
        )

        # ASR识别在守护线程中执行，避免阻塞音频回调
        def _do_asr_and_publish():
            try:
                text = self.transcribeSpeech(trimmed_audio)
                text = self._filter_asr_result(text)

                if text:
                    self._bus.publish(
                        Event(
                            event_type=EventType.DIALOG_START,
                            data={"trigger": "voice", "text": text},
                            source="AudioProcessor",
                            priority=3,
                        )
                    )
                    self._bus.publish(
                        Event(
                            event_type=EventType.NLP_TRANSCRIBE_DONE,
                            data={"text": text, "duration": trimmed_duration},
                            source="AudioProcessor",
                            priority=3,
                        )
                    )
            except Exception as e:
                logger.error(f"ASR thread error: {e}")

        threading.Thread(target=_do_asr_and_publish, daemon=True).start()

    def _trim_trailing_silence(self, audio: np.ndarray, threshold: float = 0.01) -> np.ndarray:
        """裁剪音频尾部的静音部分，保留少量过渡帧"""
        chunk_size = self._config.chunk_size
        if len(audio) <= chunk_size:
            return audio

        # 从后向前找到最后一个有能量的帧
        last_speech = len(audio)
        for i in range(len(audio) - 1, -1, -chunk_size):
            chunk = audio[max(0, i - chunk_size):i]
            energy = np.sqrt(np.mean(chunk ** 2))
            if energy > threshold:
                last_speech = i
                break

        # 保留尾部200ms作为过渡（避免截断词尾）
        keep_tail = min(int(self._config.sample_rate * 0.2), len(audio) - last_speech)
        end_idx = min(last_speech + keep_tail, len(audio))

        if end_idx < len(audio) * 0.3:
            # 裁剪太多，可能误判，返回原始
            return audio

        return audio[:end_idx]

    def detectWakeWord(self, audio_data: np.ndarray) -> tuple[bool, float]:
        return self._wakeword_manager.execute(audio_data)

    def extractFeatures(self, audio_data: np.ndarray) -> np.ndarray:
        if len(audio_data) == 0:
            return np.array([])
        energy = np.sqrt(np.mean(audio_data ** 2))
        zcr = np.mean(np.abs(np.diff(np.sign(audio_data)))) / 2
        mfcc_dim = 13
        features = np.zeros(mfcc_dim)
        features[0] = energy
        features[1] = zcr
        return features

    def vadSegment(self, audio_data: np.ndarray) -> bool:
        return self._vad_manager.execute(audio_data)

    def transcribeSpeech(self, audio_data: np.ndarray) -> str:
        max_amp = np.max(np.abs(audio_data)) if audio_data.size > 0 else 0
        if max_amp > 1e-6 and max_amp < 0.3:
            gain = min(0.9 / max_amp, 30.0)
            audio_data = np.clip(audio_data * gain, -1.0, 1.0).astype(np.float32)
            logger.debug(f"Audio normalized: {max_amp:.4f} -> {0.9:.4f} (gain={gain:.2f})")

        audio_data = audio_data.astype(np.float32)

        current_strategy = self._asr_manager._strategies.get(self._asr_manager.current)
        if current_strategy and hasattr(current_strategy, 'transcribe'):
            import inspect
            sig = inspect.signature(current_strategy.transcribe)
            if 'sample_rate' in sig.parameters:
                return current_strategy.transcribe(audio_data, sample_rate=self._config.sample_rate)
        return self._asr_manager.execute(audio_data)

    def _filter_asr_result(self, text: str) -> str:
        """
        过滤ASR识别结果中的无意义内容

        过滤规则：
        1. 过短识别（少于2个字符）直接丢弃
        2. 纯标点符号或无意义词（嗯、啊、哦、呃等）直接丢弃
        3. 连续重复字符过滤（如"嗯嗯嗯"→"嗯"）
        4. 过滤后再检查是否只剩无意义词

        Args:
            text: ASR识别结果文本

        Returns:
            过滤后的文本，无意义时返回空字符串
        """
        if not text:
            return ""

        text = text.strip()

        if len(text) < 2:
            logger.debug(f"ASR filter: text too short ('{text}'), discarded")
            return ""

        meaningless_words = [
            "嗯", "啊", "哦", "呃", "呀", "哈", "嘿", "哼", "哎",
            "嗯啊", "啊哈", "嗯嗯", "啊啊", "哦哦", "呃呃",
            "的", "了", "是", "在", "有", "和", "我", "你", "他", "她", "它",
            "这", "那", "啥", "什么", "怎么", "为什么", "干嘛",
        ]

        # 先检查：去掉所有无意义词后是否为空
        clean_text = text
        for word in meaningless_words:
            clean_text = clean_text.replace(word, "")
        clean_text = clean_text.strip()

        if not clean_text:
            logger.debug(f"ASR filter: only meaningless words ('{text}'), discarded")
            return ""

        # 连续重复字符过滤
        filtered_chars = []
        prev_char = None
        repeat_count = 0
        for char in text:
            if char == prev_char:
                repeat_count += 1
                if repeat_count < 3:
                    filtered_chars.append(char)
            else:
                filtered_chars.append(char)
                prev_char = char
                repeat_count = 1
        filtered_text = "".join(filtered_chars)

        # 过滤后再检查一次：去重后的文本去掉无意义词是否为空
        clean_filtered = filtered_text
        for word in meaningless_words:
            clean_filtered = clean_filtered.replace(word, "")
        clean_filtered = clean_filtered.strip()
        if not clean_filtered:
            logger.debug(f"ASR filter: after dedup, only meaningless words ('{filtered_text}'), discarded")
            return ""

        if filtered_text != text:
            logger.debug(f"ASR filter: repeated chars removed ('{text}' -> '{filtered_text}')")

        return filtered_text

    def set_asr_strategy(self, name: str) -> bool:
        return self._asr_manager.set_current(name)

    def stop_microphone(self) -> None:
        self._stop_microphone_stream()
        self._wake_detected = False
        self._is_recording = False
        logger.info("Microphone stream stopped (demo mode)")

    def start_microphone(self) -> None:
        if not self._running:
            return
        self._start_microphone_stream()
        logger.info("Microphone stream started")

    def start(self, start_microphone: bool = True) -> None:
        if self._running:
            return
        self._running = True
        if start_microphone:
            try:
                self._start_microphone_stream()
            except Exception as e:
                logger.error(f"Failed to start microphone stream: {e}")
                self._running = False
                raise
        logger.info(f"AudioProcessor started (microphone={'on' if start_microphone else 'off'})")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_microphone_stream()
        self._player.stop()
        
        if hasattr(self, '_music_player') and self._music_player:
            self._music_player.stop()
        
        self._wake_detected = False
        self._is_recording = False
        self._is_playing = False
        self._speech_buffer = []
        with self._playback_buffer_lock:
            self._playback_buffer = []
        self._silence_frame_count = 0
        self._aec_processor.reset()
        self._barge_in_detector.reset()
        logger.info("AudioProcessor stopped")

    def record_and_transcribe(self, max_duration: float = 10.0) -> str:
        """Push-to-talk: 录音并识别，返回文本。用于语音交互模式。"""
        asr_name = self._asr_manager.current
        if asr_name and "mock" in asr_name.lower():
            logger.warning("Cannot record: MockASR does not support real speech recognition")
            return ""

        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice not available for recording")
            return ""

        sample_rate = self._config.sample_rate
        chunk_size = self._config.chunk_size
        silence_threshold = self._config.silence_threshold
        min_silence_duration = self._config.min_silence_duration

        max_silence_frames = int(min_silence_duration * sample_rate / chunk_size)
        max_total_frames = int(max_duration * sample_rate / chunk_size)

        frames: list = []
        silence_count = 0
        has_speech = False
        recording_done = [False]

        def callback(indata, frames_count, time_info, status):
            audio = indata[:, 0] if indata.ndim > 1 else indata
            audio = audio.astype(np.float32)
            energy = float(np.sqrt(np.mean(audio ** 2)))

            nonlocal silence_count, has_speech
            if energy > silence_threshold:
                has_speech = True
                silence_count = 0
            elif has_speech:
                silence_count += 1

            frames.append(audio)
            if has_speech and silence_count >= max_silence_frames:
                recording_done[0] = True

        device_idx = self._find_input_device()

        print("  录音中... (请说话，说完停顿即可)")
        sys.stdout.flush()

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                blocksize=chunk_size,
                callback=callback,
                device=device_idx,
            ):
                total = 0
                while not recording_done[0] and total < max_total_frames:
                    sd.sleep(int(chunk_size / sample_rate * 1000))
                    total += 1

            if not has_speech:
                print("  未检测到语音输入")
                return ""

            audio_data = np.concatenate(frames)
            text = self.transcribeSpeech(audio_data)
            return text
        except Exception as e:
            logger.error(f"Recording error: {e}")
            print(f"  录音错误: {e}")
            return ""

    def _find_input_device(self):
        """查找配置的输入设备索引"""
        if self._config.input_device is not None:
            return self._config.input_device
        if self._config.input_device_name:
            from .device_finder import find_audio_device
            idx = find_audio_device(self._config.input_device_name, "input")
            if idx is not None:
                return idx
        return None

    def _start_microphone_stream(self) -> None:
        try:
            import sounddevice as sd
            self._sd_module = sd

            device_idx = None

            if self._config.input_device is not None:
                try:
                    device_info = sd.query_devices(self._config.input_device)
                    logger.info(f"Using configured input device index {self._config.input_device}: {device_info['name']}")
                    if device_info['max_input_channels'] > 0:
                        device_idx = self._config.input_device
                    else:
                        logger.warning(f"Configured input device {self._config.input_device} has no input channels, searching for available input device...")
                except Exception as e:
                    logger.warning(f"Configured input device {self._config.input_device} not found: {e}, using default...")

            if device_idx is None and self._config.input_device_name:
                device_idx = find_audio_device(self._config.input_device_name, "input")
                if device_idx is not None:
                    device_info = sd.query_devices(device_idx)
                    logger.info(f"Found input device '{self._config.input_device_name}' at index {device_idx}: {device_info['name']}")
                else:
                    logger.warning(f"Input device '{self._config.input_device_name}' not found, using default...")

            if device_idx is None:
                device_idx = sd.default.device["input"]
                device_info = sd.query_devices(device_idx)
                if device_info['max_input_channels'] > 0:
                    logger.info(f"Using system default microphone: {device_info['name']} (index: {device_idx})")
                else:
                    logger.warning(f"System default device has no input channels, searching for available input device...")
                    device_idx = None

            if device_idx is None:
                for i, dev in enumerate(sd.query_devices()):
                    if dev["max_input_channels"] > 0:
                        device_idx = i
                        device_info = dev
                        logger.info(f"Auto-selected input device: {device_info['name']} (index: {device_idx}, channels: {device_info['max_input_channels']})")
                        break

            if device_idx is None:
                logger.error("[麦克风] 未找到可用的输入设备")
                self._recording_enabled = False
                return

            self._stream = sd.InputStream(
                samplerate=self._config.sample_rate,
                channels=self._config.channels,
                blocksize=self._config.chunk_size,
                callback=self._audio_callback,
                device=device_idx,
            )
            self._stream.start()
            self._input_device_idx = device_idx
            self._recording_enabled = True
            logger.info(f"Microphone stream started: {self._config.sample_rate}Hz, {self._config.channels} channel(s), device={device_idx}")
        except ImportError:
            logger.warning("sounddevice not installed, microphone input disabled")
            self._recording_enabled = False
        except Exception as e:
            logger.error(f"[麦克风] 启动流失败: {e}")
            logger.error(f"[麦克风] 完整异常:\n{traceback.format_exc()}")
            try:
                import sounddevice as sd
                logger.info("可用音频设备:")
                for i, dev in enumerate(sd.query_devices()):
                    is_input = dev["max_input_channels"] > 0
                    if is_input:
                        logger.info(f"  Device {i}: {dev['name']} (input channels: {dev['max_input_channels']})")
            except Exception:
                pass
            self._recording_enabled = False

    def _stop_microphone_stream(self) -> None:
        if self._stream:
            try:
                logger.info("[麦克风] 正在停止并关闭流...")
                self._stream.stop()
                self._stream.close()
                logger.info("[麦克风] 流已停止并关闭")
            except BaseException as e:
                logger.error(f"[麦克风] 停止流失败: {e}")
                logger.error(f"[麦克风] 完整异常:\n{traceback.format_exc()}")
            self._stream = None
        self._recording_enabled = False

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: dict, status: int) -> None:
        if status:
            logger.warning(f"Audio stream status: {status}")

        if indata.ndim > 1:
            audio_data = indata[:, 0]
        else:
            audio_data = indata

        audio_data = audio_data.astype(np.float32)

        # 维护最近 10 帧的环形缓冲，供诊断/调试使用（带锁保护）
        with self._audio_buffer_lock:
            self._audio_buffer.append(audio_data)
            if len(self._audio_buffer) > 10:
                self._audio_buffer.pop(0)

        self.processAudio(audio_data)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def available_asr_strategies(self) -> list[str]:
        return self._asr_manager.available

    @property
    def current_asr_strategy(self) -> Optional[str]:
        return self._asr_manager.current