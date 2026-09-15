from __future__ import annotations
import os
import sys
import time
import shutil
import tempfile
import tarfile
import urllib.request
import numpy as np
from abc import abstractmethod
from typing import Optional, Tuple
from ..utils import logger, get_project_root

from ..core.strategy import Strategy


class WakeWordStrategy(Strategy):
    @abstractmethod
    def detect(self, audio_data: np.ndarray) -> Tuple[bool, float]:
        pass

    @abstractmethod
    def reset(self) -> None:
        pass


class VADStrategy(Strategy):
    @abstractmethod
    def is_speech(self, audio_data: np.ndarray) -> bool:
        pass

    @abstractmethod
    def reset(self) -> None:
        pass


class ASRStrategy(Strategy):
    @abstractmethod
    def transcribe(self, audio_data: np.ndarray) -> str:
        pass

    @abstractmethod
    def load_model(self) -> bool:
        pass


class MockWakeWord(WakeWordStrategy):
    def __init__(self, wake_word: str = "你好小智") -> None:
        self._wake_word = wake_word
        self._buffer = ""
        self._detection_count = 0
        self._energy_history = []
        self._avg_energy = 0.0
        self._min_frames_for_wake = 8
        self._base_threshold = 0.03

    @property
    def name(self) -> str:
        return "mock_wakeword"

    def detect(self, audio_data: np.ndarray) -> Tuple[bool, float]:
        energy = np.sqrt(np.mean(audio_data ** 2))

        self._energy_history.append(energy)
        if len(self._energy_history) > 30:
            self._energy_history.pop(0)
        self._avg_energy = np.mean(self._energy_history)

        threshold = max(self._base_threshold, self._avg_energy * 2.0)
        detected = energy > threshold

        if detected:
            self._detection_count += 1
            logger.debug(f"Wake detection progress: {self._detection_count}/{self._min_frames_for_wake}, energy={energy:.4f}, threshold={threshold:.4f}")
            if self._detection_count >= self._min_frames_for_wake:
                self._detection_count = 0
                logger.info(f"[唤醒检测] 检测到唤醒词! energy={energy:.4f}, threshold={threshold:.4f}, avg={self._avg_energy:.4f}")
                return True, 0.85
        # 非检测帧：不递减计数，避免接近阈值的连续检测被一帧静音清零
        # 仅当连续多帧都低于阈值且 _detection_count > 0 时才重置（带滞回）

        return False, 0.0

    def reset(self) -> None:
        self._detection_count = 0
        self._energy_history = []

    def execute(self, *args, **kwargs):
        return self.detect(*args, **kwargs)


class PorcupineWakeWord(WakeWordStrategy):
    def __init__(self, access_key: Optional[str] = None, wake_word: str = "你好小智") -> None:
        self._access_key = access_key
        self._wake_word = wake_word
        self._porcupine = None
        self._initialized = False
        self._frame_length = 512
        self._buffer = np.zeros(self._frame_length, dtype=np.float32)
        self._buffer_index = 0

    @property
    def name(self) -> str:
        return "porcupine_wakeword"

    def _init_porcupine(self) -> bool:
        if self._initialized:
            return True
        
        try:
            import pvporcupine
            import os
            
            keywords = []
            if self._wake_word == "你好小智":
                keywords.append(pvporcupine.KEYWORD_PATHS["你好小智"])
            else:
                keywords.append(self._wake_word)
            
            self._porcupine = pvporcupine.create(
                access_key=self._access_key,
                keywords=keywords,
            )
            self._frame_length = self._porcupine.frame_length
            self._buffer = np.zeros(self._frame_length, dtype=np.float32)
            self._buffer_index = 0
            self._initialized = True
            logger.info(f"Porcupine wake word engine initialized: {self._wake_word}")
            return True
        except ImportError:
            logger.warning("pvporcupine not installed, falling back to mock wake word")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Porcupine: {e}")
            return False

    def detect(self, audio_data: np.ndarray) -> Tuple[bool, float]:
        if not self._init_porcupine():
            mock_wake = MockWakeWord(self._wake_word)
            return mock_wake.detect(audio_data)

        try:
            for sample in audio_data:
                self._buffer[self._buffer_index] = sample
                self._buffer_index += 1
                
                if self._buffer_index >= self._frame_length:
                    keyword_index = self._porcupine.process(self._buffer)
                    self._buffer_index = 0
                    
                    if keyword_index >= 0:
                        logger.info(f"Porcupine wake word detected: {self._wake_word}")
                        return True, 1.0
            
            return False, 0.0
        except Exception as e:
            logger.error(f"Porcupine detection error: {e}")
            mock_wake = MockWakeWord(self._wake_word)
            return mock_wake.detect(audio_data)

    def reset(self) -> None:
        self._buffer_index = 0
        self._buffer = np.zeros(self._frame_length, dtype=np.float32)

    def execute(self, *args, **kwargs):
        return self.detect(*args, **kwargs)


class MockVAD(VADStrategy):
    def __init__(self, threshold: float = 0.01) -> None:
        self._threshold = threshold
        self._speech_frames = 0
        self._silence_frames = 0
        self._energy_history = []

    @property
    def name(self) -> str:
        return "mock_vad"

    def is_speech(self, audio_data: np.ndarray) -> bool:
        energy = np.sqrt(np.mean(audio_data ** 2))
        
        self._energy_history.append(energy)
        if len(self._energy_history) > 20:
            self._energy_history.pop(0)
        avg_energy = np.mean(self._energy_history)
        
        adaptive_threshold = max(self._threshold, avg_energy * 2)
        is_speech = energy > adaptive_threshold
        
        if is_speech:
            self._speech_frames += 1
            self._silence_frames = 0
        else:
            self._silence_frames += 1
            
        return is_speech

    def reset(self) -> None:
        self._speech_frames = 0
        self._silence_frames = 0
        self._energy_history = []

    def execute(self, *args, **kwargs):
        return self.is_speech(*args, **kwargs)


class WebRTCVAD(VADStrategy):
    def __init__(
        self,
        mode: int = 3,
        sample_rate: int = 16000,
        min_energy: float = 0.02,
        energy_multiplier: float = 2.0,
        min_speech_frames: int = 3,
    ) -> None:
        self._vad = None
        self._mode = mode
        self._speech_frames = 0
        self._silence_frames = 0
        self._initialized = False
        self._warned = False
        self._input_sample_rate = sample_rate
        self._min_energy = min_energy
        self._energy_multiplier = energy_multiplier
        self._min_speech_frames = min_speech_frames
        self._energy_history = []

    @property
    def name(self) -> str:
        return "webrtc_vad"

    def set_sample_rate(self, sample_rate: int) -> None:
        self._input_sample_rate = sample_rate

    def _init_vad(self) -> bool:
        if self._initialized:
            return True
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(self._mode)
            self._initialized = True
            logger.info(f"WebRTC VAD initialized (mode={self._mode}, input_sr={self._input_sample_rate})")
            return True
        except ImportError:
            if not self._warned:
                logger.warning("webrtcvad not installed, falling back to mock VAD")
                self._warned = True
            return False

    def is_speech(self, audio_data: np.ndarray) -> bool:
        if not self._init_vad():
            mock_vad = MockVAD()
            return mock_vad.is_speech(audio_data)

        try:
            import webrtcvad

            energy = np.sqrt(np.mean(audio_data ** 2))

            self._energy_history.append(energy)
            if len(self._energy_history) > 20:
                self._energy_history.pop(0)
            avg_energy = np.mean(self._energy_history)

            adaptive_threshold = max(self._min_energy, avg_energy * self._energy_multiplier)

            if energy < adaptive_threshold:
                self._silence_frames += 1
                self._speech_frames = 0
                return False

            target_sr = 16000

            if audio_data.dtype != np.float32:
                audio_data = audio_data.astype(np.float32)

            if self._input_sample_rate != target_sr:
                n_samples = int(len(audio_data) * target_sr / self._input_sample_rate)
                if n_samples < 1:
                    n_samples = 1
                indices = np.linspace(0, len(audio_data) - 1, n_samples)
                audio_data = np.interp(indices, np.arange(len(audio_data)), audio_data).astype(np.float32)

            int16_data = (audio_data * 32767).astype(np.int16)
            bytes_data = int16_data.tobytes()

            valid_frame_sizes = [160, 320, 480]
            frame_size = len(bytes_data)

            if frame_size not in valid_frame_sizes:
                target_frame_size = min([fs for fs in valid_frame_sizes if fs >= frame_size], default=320)
                if frame_size < target_frame_size:
                    padding = target_frame_size - frame_size
                    bytes_data = bytes_data + b'\x00' * padding
                else:
                    bytes_data = bytes_data[:target_frame_size]

            if len(bytes_data) not in valid_frame_sizes:
                if not self._warned:
                    logger.warning(f"WebRTC VAD frame size {len(bytes_data)} not valid, falling back to mock VAD")
                    self._warned = True
                mock_vad = MockVAD()
                return mock_vad.is_speech(audio_data)

            is_speech = self._vad.is_speech(bytes_data, target_sr)

            if is_speech:
                self._speech_frames += 1
                self._silence_frames = 0
            else:
                self._silence_frames += 1

            return is_speech
        except Exception as e:
            if not self._warned:
                logger.error(f"WebRTC VAD error: {e}, falling back to mock VAD")
                self._warned = True
            mock_vad = MockVAD()
            return mock_vad.is_speech(audio_data)

    def reset(self) -> None:
        self._speech_frames = 0
        self._silence_frames = 0
        self._energy_history = []

    def execute(self, *args, **kwargs):
        return self.is_speech(*args, **kwargs)


class MockASR(ASRStrategy):
    def __init__(self) -> None:
        self._model_loaded = False

    @property
    def name(self) -> str:
        return "mock_asr"

    def load_model(self) -> bool:
        self._model_loaded = True
        logger.info("Mock ASR model loaded (placeholder only)")
        return True

    def transcribe(self, audio_data: np.ndarray) -> str:
        if not self._model_loaded:
            self.load_model()
        return ""

    def execute(self, *args, **kwargs):
        return self.transcribe(*args, **kwargs)


class WhisperASR(ASRStrategy):
    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size
        self._model = None
        self._model_loaded = False
        self._target_sr = 16000

    @property
    def name(self) -> str:
        return f"whisper_{self._model_size}"

    def load_model(self) -> bool:
        try:
            import whisper

            self._model = whisper.load_model(self._model_size)
            self._model_loaded = True
            logger.info(f"Whisper model loaded: {self._model_size}")
            return True
        except ImportError:
            logger.warning("Whisper not installed, using mock ASR")
            return False
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            return False

    def _resample(self, audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        if src_sr == dst_sr:
            return audio
        try:
            from scipy.signal import resample
            num_samples = int(len(audio) * dst_sr / src_sr)
            return resample(audio, num_samples).astype(np.float32)
        except ImportError:
            ratio = dst_sr / src_sr
            indices = np.arange(int(len(audio) * ratio)) / ratio
            indices = np.clip(indices.astype(int), 0, len(audio) - 1)
            return audio[indices].astype(np.float32)

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        if not self._model_loaded:
            if not self.load_model():
                return ""
        try:
            audio = audio_data.astype(np.float32)
            if audio.ndim > 1:
                audio = audio[:, 0]

            if sample_rate != self._target_sr:
                audio = self._resample(audio, sample_rate, self._target_sr)

            max_val = np.max(np.abs(audio))
            if max_val > 0 and max_val < 0.01:
                logger.warning(f"Audio too quiet (max={max_val:.4f}), amplification may help")
                audio = audio * (0.1 / max_val)

            result = self._model.transcribe(
                audio,
                language="zh",
                fp16=False,
                verbose=False,
            )
            text = result["text"].strip()
            logger.info(f"Whisper ASR: '{text}' (confidence approx)")
            return text
        except Exception as e:
            logger.error(f"ASR transcription error: {e}")
            return ""

    def execute(self, *args, **kwargs):
        return self.transcribe(*args, **kwargs)


class SherpaOnnxASR(ASRStrategy):
    """sherpa-onnx 离线语音识别（支持 paraformer 中文模型自动下载）"""

    MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-2023-09-14.tar.bz2"
    MODEL_DIR_NAME = "sherpa-onnx-paraformer-zh-2023-09-14"

    def __init__(self, model_dir: str = "", model_type: str = "paraformer", auto_download: bool = False) -> None:
        self._model_dir = model_dir
        self._model_type = model_type
        self._auto_download = auto_download
        self._recognizer = None
        self._model_loaded = False
        self._target_sr = 16000

    @property
    def name(self) -> str:
        return "sherpa_onnx_asr"

    def _find_model_dir(self) -> str:
        if self._model_dir and os.path.exists(self._model_dir):
            return self._model_dir
        project_root = get_project_root()
        search_dirs = [
            os.path.join(project_root, "models", "asr"),
            os.path.join("models", "asr"),
        ]
        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            exact = os.path.join(search_dir, self.MODEL_DIR_NAME)
            if os.path.exists(exact):
                return exact
            for name in os.listdir(search_dir):
                full = os.path.join(search_dir, name)
                if os.path.isdir(full) and name.startswith("sherpa-onnx-paraformer"):
                    if os.path.exists(os.path.join(full, "model.int8.onnx")) or \
                       os.path.exists(os.path.join(full, "model.onnx")):
                        return full
        return ""

    def _download_progress(self, block_num: int, block_size: int, total_size: int) -> None:
        if total_size > 0:
            downloaded = block_num * block_size
            percent = min(downloaded / total_size * 100, 100)
            if block_num % 100 == 0 or percent >= 100:
                logger.info(f"ASR模型下载进度: {percent:.1f}% ({downloaded // (1024*1024)}MB / {total_size // (1024*1024)}MB)")

    def _download_model(self) -> str:
        project_root = get_project_root()
        asr_dir = os.path.join(project_root, "models", "asr")
        os.makedirs(asr_dir, exist_ok=True)
        model_dir = os.path.join(asr_dir, self.MODEL_DIR_NAME)
        tmp_path = os.path.join(asr_dir, self.MODEL_DIR_NAME + ".tar.bz2")
        logger.info(f"开始下载 paraformer ASR 模型（约227MB）: {self.MODEL_URL}")
        try:
            urllib.request.urlretrieve(self.MODEL_URL, tmp_path, reporthook=self._download_progress)
            logger.info("模型下载完成，开始解压...")
            with tarfile.open(tmp_path, "r:bz2") as tar:
                tar.extractall(asr_dir)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            if os.path.exists(model_dir):
                logger.info(f"模型已解压到: {model_dir}")
                return model_dir
            for name in os.listdir(asr_dir):
                full = os.path.join(asr_dir, name)
                if os.path.isdir(full) and name.startswith("sherpa-onnx-paraformer"):
                    return full
            return ""
        except Exception as e:
            logger.error(f"下载 ASR 模型失败: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return ""

    def _load_paraformer(self, model_dir: str) -> bool:
        """加载 paraformer 模型，尝试多种 API 兼容不同版本"""
        try:
            import sherpa_onnx
        except ImportError:
            return False

        model_path = os.path.join(model_dir, "model.int8.onnx")
        if not os.path.exists(model_path):
            model_path = os.path.join(model_dir, "model.onnx")
        tokens_path = os.path.join(model_dir, "tokens.txt")

        if not os.path.exists(model_path) or not os.path.exists(tokens_path):
            logger.error(f"模型文件不完整: model={model_path}, tokens={tokens_path}")
            return False

        logger.info(f"尝试加载 paraformer 模型: {model_path}")

        # 方式1: 配置对象方式（和 TTS 一样的风格）
        try:
            if hasattr(sherpa_onnx, 'OfflineRecognizerConfig') and \
               hasattr(sherpa_onnx, 'OfflineModelConfig'):

                paraformer_cfg = None
                paraformer_cfg_name = None

                for cfg_name in [
                    'OfflineParaformerModelConfig',
                    'ParaformerModelConfig',
                    'OfflineParaformerConfig',
                ]:
                    if hasattr(sherpa_onnx, cfg_name):
                        paraformer_cfg_name = cfg_name
                        break

                if paraformer_cfg_name is None:
                    logger.warning("未找到 paraformer 配置类，尝试检测所有 Offline 配置类")
                    all_cfg = [x for x in dir(sherpa_onnx) if 'Config' in x and 'Offline' in x]
                    logger.debug(f"所有 Offline Config 类: {all_cfg}")
                else:
                    logger.info(f"找到 paraformer 配置类: {paraformer_cfg_name}")

                    ParaformerCfgClass = getattr(sherpa_onnx, paraformer_cfg_name)

                    import inspect
                    try:
                        sig = inspect.signature(ParaformerCfgClass.__init__)
                        param_names = list(sig.parameters.keys())
                        logger.debug(f"{paraformer_cfg_name} 参数: {param_names}")
                    except (ValueError, TypeError):
                        param_names = []

                    model_kw = {}
                    for pname in ['model', 'model_path', 'path', 'paraformer']:
                        if pname in param_names or not param_names:
                            model_kw[pname] = model_path
                            break
                    if not model_kw:
                        model_kw['model'] = model_path

                    try:
                        paraformer_cfg = ParaformerCfgClass(**model_kw)
                    except TypeError as e:
                        logger.debug(f"创建 {paraformer_cfg_name} 失败: {e}，尝试不同参数名")
                        for alt_kw in [
                            {'model': model_path},
                            {'model_path': model_path},
                            {'path': model_path},
                        ]:
                            try:
                                paraformer_cfg = ParaformerCfgClass(**alt_kw)
                                break
                            except TypeError:
                                continue

                if paraformer_cfg is not None:
                    try:
                        import inspect
                        sig = inspect.signature(sherpa_onnx.OfflineModelConfig.__init__)
                        model_cfg_params = list(sig.parameters.keys())
                        logger.debug(f"OfflineModelConfig 参数: {model_cfg_params}")
                    except (ValueError, TypeError):
                        model_cfg_params = []

                    model_cfg_kw = {
                        'tokens': tokens_path,
                        'num_threads': 2,
                        'provider': "cpu",
                    }

                    if 'paraformer' in model_cfg_params or not model_cfg_params:
                        model_cfg_kw['paraformer'] = paraformer_cfg

                    try:
                        model_cfg = sherpa_onnx.OfflineModelConfig(**model_cfg_kw)
                    except TypeError as e:
                        logger.debug(f"创建 OfflineModelConfig 失败: {e}")
                        model_cfg = None

                    if model_cfg is not None:
                        try:
                            recognizer_cfg = sherpa_onnx.OfflineRecognizerConfig(model=model_cfg)
                            self._recognizer = sherpa_onnx.OfflineRecognizer(recognizer_cfg)
                            logger.info("配置对象方式加载成功")
                            return True
                        except Exception as e:
                            logger.debug(f"创建 OfflineRecognizer 失败: {e}")
        except Exception as e:
            logger.debug(f"配置对象方式加载失败: {e}")

        # 方式2: from_paraformer 工厂方法
        try:
            if hasattr(sherpa_onnx.OfflineRecognizer, 'from_paraformer'):
                logger.info("尝试 from_paraformer 工厂方法")
                import inspect
                try:
                    sig = inspect.signature(sherpa_onnx.OfflineRecognizer.from_paraformer)
                    logger.debug(f"from_paraformer 参数: {list(sig.parameters.keys())}")
                except (ValueError, TypeError):
                    pass

                param_combos = [
                    {'paraformer': model_path, 'tokens': tokens_path},
                    {'model': model_path, 'tokens': tokens_path},
                    {'model_path': model_path, 'tokens': tokens_path},
                    {'paraformer_model': model_path, 'tokens': tokens_path},
                    {'paraformer': model_path, 'tokens': tokens_path, 'num_threads': 2},
                    {'model': model_path, 'tokens': tokens_path, 'num_threads': 2},
                ]

                for kw in param_combos:
                    try:
                        self._recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(**kw)
                        logger.info(f"from_paraformer 方式加载成功 (参数: {list(kw.keys())})")
                        return True
                    except TypeError:
                        continue
                    except Exception as e:
                        logger.debug(f"from_paraformer 参数 {list(kw.keys())} 失败: {e}")
                        continue
        except Exception as e:
            logger.debug(f"from_paraformer 方式加载失败: {e}")

        # 方式3: 直接检查所有 from_* 工厂方法
        try:
            factory_methods = [m for m in dir(sherpa_onnx.OfflineRecognizer) if m.startswith('from_')]
            logger.debug(f"OfflineRecognizer 工厂方法: {factory_methods}")
        except Exception:
            pass

        logger.error("所有 paraformer 加载方式均失败")
        return False

    def load_model(self) -> bool:
        if self._model_loaded:
            return True
        try:
            import sherpa_onnx
        except ImportError:
            logger.warning("sherpa-onnx 未安装，ASR 不可用")
            return False

        model_dir = self._find_model_dir()
        if not model_dir:
            if self._auto_download:
                logger.info("未找到 paraformer 模型，开始自动下载...")
                model_dir = self._download_model()
            else:
                logger.info("未找到 paraformer 模型，自动下载已禁用，使用 mock 模式")
                return False

        if not model_dir or not os.path.exists(model_dir):
            logger.warning(f"SherpaOnnx ASR: 模型目录不存在: {model_dir}")
            return False

        if self._model_type == "paraformer":
            if self._load_paraformer(model_dir):
                self._model_loaded = True
                logger.info(f"SherpaOnnx ASR 加载完成: {model_dir} (paraformer)")
                return True
            return False

        logger.warning(f"SherpaOnnx ASR: 不支持的模型类型 {self._model_type}，请使用 paraformer")
        return False

    def _resample(self, audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        if src_sr == dst_sr:
            return audio
        try:
            from scipy.signal import resample
            num = int(len(audio) * dst_sr / src_sr)
            return resample(audio, num).astype(np.float32)
        except ImportError:
            ratio = dst_sr / src_sr
            idx = np.arange(int(len(audio) * ratio)) / ratio
            idx = np.clip(idx.astype(int), 0, len(audio) - 1)
            return audio[idx].astype(np.float32)

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        if not self._model_loaded:
            if not self.load_model():
                return ""
        try:
            audio = audio_data.astype(np.float32)
            if audio.ndim > 1:
                audio = audio[:, 0]
            if sample_rate != self._target_sr:
                audio = self._resample(audio, sample_rate, self._target_sr)

            stream = self._recognizer.create_stream()
            stream.accept_waveform(self._target_sr, audio)
            self._recognizer.decode_stream(stream)
            text = stream.result.text.strip()
            logger.info(f"SherpaOnnx ASR: '{text}'")
            return text
        except Exception as e:
            logger.error(f"SherpaOnnx ASR 错误: {e}")
            return ""

    def execute(self, *args, **kwargs):
        return self.transcribe(*args, **kwargs)


class ParaformerASR(ASRStrategy):
    """Paraformer 离线语音识别（直接用 onnxruntime，不依赖 sherpa-onnx ASR API）"""

    MODEL_DIR_NAME = "sherpa-onnx-paraformer-zh-2023-09-14"

    def __init__(self, model_dir: str = "") -> None:
        self._model_dir = model_dir
        self._session = None
        self._model_loaded = False
        self._target_sr = 16000
        self._tokens = {}
        self._neg_mean = None
        self._inv_std = None
        self._fbank_opts = None

    @property
    def name(self) -> str:
        return "paraformer_onnx"

    def _find_model_dir(self) -> str:
        if self._model_dir and os.path.exists(self._model_dir):
            return self._model_dir
        project_root = get_project_root()
        search_dirs = [
            os.path.join(project_root, "models", "asr"),
            os.path.join("models", "asr"),
        ]
        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            exact = os.path.join(search_dir, self.MODEL_DIR_NAME)
            if os.path.exists(exact):
                return exact
            for name in os.listdir(search_dir):
                full = os.path.join(search_dir, name)
                if os.path.isdir(full) and name.startswith("sherpa-onnx-paraformer"):
                    if os.path.exists(os.path.join(full, "model.int8.onnx")) or \
                       os.path.exists(os.path.join(full, "model.onnx")):
                        return full
        return ""

    def _load_tokens(self, tokens_path: str) -> bool:
        try:
            i = 0
            with open(tokens_path, encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split()
                    if parts:
                        self._tokens[i] = parts[0]
                    i += 1
            return True
        except Exception as e:
            logger.error(f"加载 tokens 失败: {e}")
            return False

    def _load_cmvn(self, mvn_path: str) -> bool:
        try:
            neg_mean = None
            inv_std = None
            with open(mvn_path) as f:
                for line in f:
                    if not line.startswith("<LearnRateCoef>"):
                        continue
                    t = line.split()[3:-1]
                    t = list(map(lambda x: float(x), t))
                    if neg_mean is None:
                        neg_mean = np.array(t, dtype=np.float32)
                    else:
                        inv_std = np.array(t, dtype=np.float32)
            if neg_mean is not None and inv_std is not None:
                self._neg_mean = neg_mean
                self._inv_std = inv_std
                return True
            return False
        except Exception as e:
            logger.error(f"加载 cmvn 失败: {e}")
            return False

    def load_model(self) -> bool:
        if self._model_loaded:
            return True
        try:
            import onnxruntime as ort
        except ImportError:
            logger.warning("onnxruntime 未安装，Paraformer ASR 不可用")
            return False

        model_dir = self._find_model_dir()
        if not model_dir:
            logger.warning("未找到 paraformer 模型目录")
            return False

        model_path = os.path.join(model_dir, "model.int8.onnx")
        if not os.path.exists(model_path):
            model_path = os.path.join(model_dir, "model.onnx")
        tokens_path = os.path.join(model_dir, "tokens.txt")
        mvn_path = os.path.join(model_dir, "am.mvn")

        if not os.path.exists(model_path):
            logger.error(f"模型文件不存在: {model_path}")
            return False
        if not os.path.exists(tokens_path):
            logger.error(f"tokens 文件不存在: {tokens_path}")
            return False

        logger.info(f"加载 Paraformer 模型: {model_path}")

        try:
            session_opts = ort.SessionOptions()
            session_opts.log_severity_level = 3
            session_opts.intra_op_num_threads = 2
            self._session = ort.InferenceSession(model_path, session_opts)
        except Exception as e:
            logger.error(f"加载 ONNX 模型失败: {e}")
            return False

        if not self._load_tokens(tokens_path):
            return False

        if os.path.exists(mvn_path):
            self._load_cmvn(mvn_path)
        else:
            logger.warning("未找到 am.mvn，跳过 CMVN")

        try:
            import kaldi_native_fbank as knf
            opts = knf.FbankOptions()
            opts.frame_opts.dither = 0
            opts.frame_opts.snip_edges = False
            opts.frame_opts.samp_freq = self._target_sr
            opts.mel_opts.num_bins = 80
            self._fbank_opts = opts
        except ImportError:
            logger.warning("kaldi_native_fbank 未安装，尝试使用 librosa 替代")
            self._fbank_opts = None

        self._model_loaded = True
        logger.info(f"Paraformer ASR 加载完成: {model_path}")
        return True

    def _compute_features(self, audio: np.ndarray) -> np.ndarray:
        """计算 FBANK 特征并做 LFR 和 CMVN"""
        try:
            import kaldi_native_fbank as knf
            opts = self._fbank_opts
            online_fbank = knf.OnlineFbank(opts)
            samples = (audio * 32768).tolist()
            online_fbank.accept_waveform(self._target_sr, samples)
            online_fbank.input_finished()

            features = np.stack(
                [online_fbank.get_frame(i) for i in range(online_fbank.num_frames_ready)]
            ).astype(np.float32)
        except ImportError:
            try:
                import librosa
                n_fft = 512
                hop_length = 160
                n_mels = 80
                S = librosa.feature.melspectrogram(
                    y=audio, sr=self._target_sr,
                    n_fft=n_fft, hop_length=hop_length,
                    n_mels=n_mels, fmin=20, fmax=7600,
                )
                features = librosa.power_to_db(S).T.astype(np.float32)
            except ImportError:
                logger.error("没有可用的特征提取库（kaldi_native_fbank 或 librosa）")
                return np.array([], dtype=np.float32)

        if features.size == 0:
            return features

        window_size = 7
        window_shift = 6
        T = (features.shape[0] - window_size) // window_shift + 1
        if T <= 0:
            pad = np.zeros((window_size - features.shape[0], features.shape[1]), dtype=np.float32)
            features = np.concatenate([features, pad], axis=0)
            T = 1

        features = np.lib.stride_tricks.as_strided(
            features,
            shape=(T, features.shape[1] * window_size),
            strides=((window_shift * features.shape[1]) * 4, 4),
        ).copy()

        if self._neg_mean is not None and self._inv_std is not None:
            if features.shape[1] == len(self._neg_mean):
                features = (features + self._neg_mean) * self._inv_std

        return features.astype(np.float32)

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        if not self._model_loaded:
            if not self.load_model():
                return ""
        try:
            audio = audio_data.astype(np.float32)
            if audio.ndim > 1:
                audio = audio[:, 0]
            if sample_rate != self._target_sr:
                audio = self._resample(audio, sample_rate, self._target_sr)

            if len(audio) < 1600:
                return ""

            features = self._compute_features(audio)
            if features.size == 0 or features.shape[0] == 0:
                return ""

            features = np.expand_dims(features, axis=0)
            features_length = np.array([features.shape[1]], dtype=np.int32)

            inputs = {
                "speech": features,
                "speech_lengths": features_length,
            }
            output_names = ["logits", "token_num"]

            outputs = self._session.run(output_names, input_feed=inputs)
            log_probs = outputs[0][0]
            token_num = int(outputs[1][0])

            if token_num <= 0:
                return ""

            y = log_probs.argmax(axis=-1)[:token_num]

            text = "".join([self._tokens.get(int(i), "") for i in y if int(i) not in (0, 2)])
            logger.info(f"Paraformer ASR: '{text}'")
            return text
        except Exception as e:
            logger.error(f"Paraformer ASR 识别错误: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return ""

    def _resample(self, audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        if src_sr == dst_sr:
            return audio
        try:
            from scipy.signal import resample
            num = int(len(audio) * dst_sr / src_sr)
            return resample(audio, num).astype(np.float32)
        except ImportError:
            ratio = dst_sr / src_sr
            idx = np.arange(int(len(audio) * ratio)) / ratio
            idx = np.clip(idx.astype(int), 0, len(audio) - 1)
            return audio[idx].astype(np.float32)

    def execute(self, *args, **kwargs):
        return self.transcribe(*args, **kwargs)


class FasterWhisperASR(ASRStrategy):
    """faster-whisper 语音识别（比 openai-whisper 更快更轻量）"""

    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size
        self._model = None
        self._model_loaded = False
        self._target_sr = 16000

    @property
    def name(self) -> str:
        return f"faster_whisper_{self._model_size}"

    def _check_network(self, timeout: float = 5.0) -> bool:
        """检测 huggingface.co 是否可达，避免加载时卡住"""
        import socket
        try:
            sock = socket.create_connection(("huggingface.co", 443), timeout=timeout)
            sock.close()
            return True
        except (socket.timeout, OSError) as e:
            logger.warning(f"无法连接 huggingface.co: {e}，跳过 faster-whisper 加载")
            return False

    def load_model(self) -> bool:
        if self._model_loaded:
            return True
        # 先检测网络，不通就直接返回，避免卡住
        if not self._check_network():
            return False
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
            self._model_loaded = True
            logger.info(f"FasterWhisper 模型加载完成: {self._model_size}")
            return True
        except ImportError:
            logger.warning("faster-whisper 未安装，请执行: pip install faster-whisper")
            return False
        except Exception as e:
            logger.error(f"FasterWhisper 加载错误: {e}")
            return False

    def _resample(self, audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        if src_sr == dst_sr:
            return audio
        try:
            from scipy.signal import resample
            num = int(len(audio) * dst_sr / src_sr)
            return resample(audio, num).astype(np.float32)
        except ImportError:
            ratio = dst_sr / src_sr
            idx = np.arange(int(len(audio) * ratio)) / ratio
            idx = np.clip(idx.astype(int), 0, len(audio) - 1)
            return audio[idx].astype(np.float32)

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        if not self._model_loaded:
            if not self.load_model():
                return ""
        try:
            audio = audio_data.astype(np.float32)
            if audio.ndim > 1:
                audio = audio[:, 0]
            if sample_rate != self._target_sr:
                audio = self._resample(audio, sample_rate, self._target_sr)

            segments, info = self._model.transcribe(audio, language="zh", beam_size=5)
            text = "".join(seg.text for seg in segments).strip()
            logger.info(f"FasterWhisper ASR: '{text}'")
            return text
        except Exception as e:
            logger.error(f"FasterWhisper ASR 错误: {e}")
            return ""

    def execute(self, *args, **kwargs):
        return self.transcribe(*args, **kwargs)
