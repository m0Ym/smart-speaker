from __future__ import annotations
import numpy as np
from abc import abstractmethod
from typing import Optional, Tuple
from ..utils.logger import logger

from ..core.strategy import Strategy


class TTSStrategy(Strategy):
    @abstractmethod
    def synthesize(self, text: str) -> np.ndarray:
        pass

    @abstractmethod
    def get_sample_rate(self) -> int:
        pass


class MockTTS(TTSStrategy):
    def __init__(self) -> None:
        self._sample_rate = 16000

    @property
    def name(self) -> str:
        return "mock_tts"

    def synthesize(self, text: str) -> np.ndarray:
        duration = len(text) * 0.15
        t = np.linspace(0, duration, int(self._sample_rate * duration), dtype=np.float32)
        audio = 0.1 * np.sin(2 * np.pi * 440 * t) * np.exp(-t * 0.5)
        return audio

    def get_sample_rate(self) -> int:
        return self._sample_rate

    def execute(self, *args, **kwargs):
        return self.synthesize(*args, **kwargs)


class EdgeTTSTTS(TTSStrategy):
    """微软 Edge 神经网络 TTS - 在线模式，质量最高"""

    VOICES = {
        "xiaoxiao": "zh-CN-XiaoxiaoNeural",
        "yunxi": "zh-CN-YunxiNeural",
        "xiaoyi": "zh-CN-XiaoyiNeural",
        "yunjian": "zh-CN-YunjianNeural",
        "xiaohan": "zh-CN-XiaohanNeural",
        "xiaomeng": "zh-CN-XiaomengNeural",
        "xiaomo": "zh-CN-XiaomoNeural",
        "xiaoqiu": "zh-CN-XiaoqiuNeural",
        "xiaorui": "zh-CN-XiaoruiNeural",
        "xiaoshuang": "zh-CN-XiaoshuangNeural",
        "xiaoxuan": "zh-CN-XiaoxuanNeural",
        "xiaoyan": "zh-CN-XiaoyanNeural",
        "xiaozhen": "zh-CN-XiaozhenNeural",
    }

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        volume: str = "+0%",
    ) -> None:
        self._sample_rate = 24000
        self._voice = voice
        self._rate = rate
        self._volume = volume
        self._available = None

    @property
    def name(self) -> str:
        return "edge_tts"

    def _check_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import edge_tts  # noqa: F401
            import soundfile  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    def synthesize(self, text: str) -> np.ndarray:
        if not self._check_available():
            raise RuntimeError("edge-tts or soundfile not installed")

        import asyncio
        import edge_tts
        import soundfile as sf
        import io

        async def generate():
            communicate = edge_tts.Communicate(
                text, self._voice,
                rate=self._rate,
                volume=self._volume,
            )
            audio_bytes = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes.write(chunk["data"])
            audio_bytes.seek(0)
            return audio_bytes.getvalue()

        try:
            loop = asyncio.new_event_loop()
            # Set timeout to prevent long waiting on network issues
            audio_data = loop.run_until_complete(
                asyncio.wait_for(generate(), timeout=15.0)
            )
            loop.close()
        except asyncio.TimeoutError:
            loop.close()
            raise RuntimeError("Edge TTS timeout (15s)")
        except Exception as e:
            loop.close()
            raise RuntimeError(f"Edge TTS network error: {e}")

        if not audio_data:
            raise RuntimeError("Edge TTS returned empty audio")

        audio_bytes = io.BytesIO(audio_data)
        audio, sr = sf.read(audio_bytes)
        self._sample_rate = sr

        if isinstance(audio, np.ndarray) and audio.ndim == 2:
            audio = audio[:, 0]

        logger.info(f"Edge TTS synthesized: {len(audio)} samples at {self._sample_rate}Hz (voice={self._voice})")
        return audio.astype(np.float32)

    def get_sample_rate(self) -> int:
        return self._sample_rate

    def execute(self, *args, **kwargs):
        return self.synthesize(*args, **kwargs)


class SherpaOnnxTTS(TTSStrategy):
    """sherpa-onnx VITS 端侧神经网络 TTS - 离线模式，高质量"""

    def __init__(self, model_path: Optional[str] = None, voice_id: int = 0) -> None:
        self._sample_rate = 22050
        self._model_path = model_path
        self._voice_id = voice_id
        self._tts = None
        self._initialized = False
        self._available = None
        self._resolved_model_path = None

    @property
    def name(self) -> str:
        return "sherpa_onnx_tts"

    def _check_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import sherpa_onnx  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    def _init_engine(self) -> bool:
        if self._initialized:
            return True
        if not self._check_available():
            return False
        try:
            import sherpa_onnx
            import os
            import glob

            model_path = self._model_path
            if not model_path or not os.path.exists(model_path):
                logger.info("Configured TTS model path invalid, searching for VITS model...")
                from ..utils import get_project_root
                project_root = get_project_root()
                search_dirs = [
                    os.path.join(project_root, "models", "vits-zh"),
                    os.path.join(project_root, "models", "vits"),
                    os.path.join(project_root, "models", "tts"),
                ]
                for search_dir in search_dirs:
                    if os.path.exists(search_dir) and glob.glob(os.path.join(search_dir, "*.onnx")):
                        model_path = search_dir
                        logger.info(f"Auto-discovered VITS model: {model_path}")
                        break

            if not model_path or not os.path.exists(model_path):
                logger.warning("No VITS model found, Sherpa-ONNX TTS unavailable")
                return False

            self._resolved_model_path = model_path

            onnx_files = glob.glob(os.path.join(model_path, "*.onnx"))
            if not onnx_files:
                logger.warning(f"No .onnx file found in {model_path}")
                return False
            model_file = onnx_files[0]

            tokens_file = os.path.join(model_path, "tokens.txt")
            if not os.path.exists(tokens_file):
                logger.warning(f"tokens.txt not found: {tokens_file}")
                return False

            lexicon_file = os.path.join(model_path, "lexicon.txt")

            rule_fsts = []
            for fst in ["phone.fst", "date.fst", "number.fst"]:
                fst_path = os.path.join(model_path, fst)
                if os.path.exists(fst_path):
                    rule_fsts.append(fst_path)
            rule_fsts_str = ",".join(rule_fsts) if rule_fsts else ""

            # Build config using proper sherpa_onnx API
            vits_config = sherpa_onnx.OfflineTtsVitsModelConfig(
                model=model_file,
                lexicon=lexicon_file if os.path.exists(lexicon_file) else "",
                data_dir="",  # Not needed for Chinese piper model
                tokens=tokens_file,
            )
            
            model_config = sherpa_onnx.OfflineTtsModelConfig(
                vits=vits_config,
                provider="cpu",
                debug=False,
                num_threads=2,
            )
            
            tts_config = sherpa_onnx.OfflineTtsConfig(
                model=model_config,
                rule_fsts=rule_fsts_str,
                max_num_sentences=1,
            )
            
            if not tts_config.validate():
                logger.warning("sherpa-onnx TTS config validation failed")
                return False
            
            self._tts = sherpa_onnx.OfflineTts(tts_config)
            self._sample_rate = self._tts.sample_rate
            self._initialized = True
            logger.info(
                f"Sherpa-ONNX TTS initialized: {model_path} "
                f"(sr={self._sample_rate}, model={os.path.basename(model_file)})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to init sherpa-onnx: {e}")
            return False

    def synthesize(self, text: str) -> np.ndarray:
        if not self._init_engine():
            raise RuntimeError("sherpa-onnx not available")

        import sherpa_onnx
        
        gen_config = sherpa_onnx.GenerationConfig()
        gen_config.sid = self._voice_id
        gen_config.speed = 1.0
        
        audio = self._tts.generate(text, gen_config)
        samples = np.array(audio.samples, dtype=np.float32)

        logger.info(
            f"Sherpa-ONNX TTS synthesized: {len(samples)} samples "
            f"at {self._sample_rate}Hz (sid={self._voice_id})"
        )
        return samples

    def get_sample_rate(self) -> int:
        return self._sample_rate

    def execute(self, *args, **kwargs):
        return self.synthesize(*args, **kwargs)


class Pyttsx3TTS(TTSStrategy):
    """pyttsx3 TTS - 离线模式，依赖系统语音引擎"""

    def __init__(self) -> None:
        self._engine = None
        self._sample_rate = 22050
        self._initialized = False
        self._available = None

    @property
    def name(self) -> str:
        return "pyttsx3_tts"

    def _check_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import pyttsx3  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    def _init_engine(self) -> bool:
        if self._initialized:
            return True
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            voices = self._engine.getProperty("voices")
            for voice in voices:
                try:
                    lang = getattr(voice, 'language', '')
                    name = getattr(voice, 'name', '')
                    id = getattr(voice, 'id', '')
                    if ("zh" in str(lang).lower() or "chinese" in str(lang).lower() or
                        "zh" in str(name).lower() or "chinese" in str(name).lower() or
                        "zh" in str(id).lower()):
                        self._engine.setProperty("voice", voice.id)
                        logger.info(f"Selected Chinese voice: {name} ({lang})")
                        break
                except Exception:
                    pass
            self._engine.setProperty("rate", 160)
            self._engine.setProperty("volume", 1.0)
            self._initialized = True
            logger.info("Pyttsx3 TTS engine initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize pyttsx3: {e}")
            return False

    def synthesize(self, text: str) -> np.ndarray:
        if not self._check_available() or not self._init_engine():
            raise RuntimeError("pyttsx3 not available")

        import wave
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        try:
            self._engine.save_to_file(text, temp_path)
            self._engine.runAndWait()

            if not os.path.exists(temp_path):
                raise FileNotFoundError(f"Temp file not created: {temp_path}")

            file_size = os.path.getsize(temp_path)
            if file_size < 100:
                raise ValueError(f"WAV file too small ({file_size} bytes), likely corrupted")

            with wave.open(temp_path, "rb") as wf:
                num_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                self._sample_rate = wf.getframerate()
                num_frames = wf.getnframes()
                raw_data = wf.readframes(num_frames)

            if sample_width == 2:
                dtype = np.int16
            elif sample_width == 4:
                dtype = np.int32
            else:
                dtype = np.float32

            audio = np.frombuffer(raw_data, dtype=dtype)
            audio = audio.astype(np.float32) / np.iinfo(dtype).max

            if num_channels > 1:
                audio = audio.reshape(-1, num_channels)[:, 0]

            logger.info(f"Pyttsx3 TTS synthesized: {len(audio)} samples at {self._sample_rate}Hz")
            return audio
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def get_sample_rate(self) -> int:
        return self._sample_rate

    def execute(self, *args, **kwargs):
        return self.synthesize(*args, **kwargs)


class EspeakNGTTS(TTSStrategy):
    """espeak-ng TTS - 最后回退方案，质量较低但保证可用"""

    def __init__(self, voice: str = "zh") -> None:
        self._sample_rate = 22050
        self._available = None
        self._binary = None
        self._voice = voice

    @property
    def name(self) -> str:
        return "espeak_ng_tts"

    def _check_available(self) -> bool:
        if self._available is not None:
            return self._available
        import subprocess
        for binary in ["espeak-ng", "espeak"]:
            try:
                result = subprocess.run(
                    [binary, "--version"],
                    capture_output=True, text=True, timeout=3
                )
                if result.returncode == 0:
                    self._binary = binary
                    self._available = True
                    logger.info(f"Found TTS binary: {binary} ({result.stdout.strip()})")
                    return True
            except Exception:
                continue
        self._available = False
        return False

    def synthesize(self, text: str) -> np.ndarray:
        if not self._check_available():
            raise RuntimeError("espeak-ng/espeak not available")

        import wave
        import tempfile
        import os
        import subprocess

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        try:
            cmd = [
                self._binary,
                "-v", self._voice,
                "-s", "160",
                "-p", "40",
                "-g", "5",
                "-a", "200",
                "-w", temp_path,
                text
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise RuntimeError(f"{self._binary} failed: {result.stderr}")

            if not os.path.exists(temp_path):
                raise FileNotFoundError(f"{self._binary} did not create output file")

            file_size = os.path.getsize(temp_path)
            if file_size < 100:
                raise ValueError(f"Output too small ({file_size} bytes)")

            with wave.open(temp_path, "rb") as wf:
                num_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                self._sample_rate = wf.getframerate()
                num_frames = wf.getnframes()
                raw_data = wf.readframes(num_frames)

            if sample_width == 2:
                dtype = np.int16
            elif sample_width == 4:
                dtype = np.int32
            else:
                dtype = np.float32

            audio = np.frombuffer(raw_data, dtype=dtype)
            audio = audio.astype(np.float32) / np.iinfo(dtype).max

            if num_channels > 1:
                audio = audio.reshape(-1, num_channels)[:, 0]

            logger.info(f"eSpeak TTS synthesized: {len(audio)} samples at {self._sample_rate}Hz")
            return audio
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def get_sample_rate(self) -> int:
        return self._sample_rate

    def execute(self, *args, **kwargs):
        return self.synthesize(*args, **kwargs)


class AutoTTS(TTSStrategy):
    """自动选择最佳可用 TTS 引擎，离线优先"""

    GENDER_MAP = {
        "female": {"sherpa_sid": 0, "espeak_voice": "zh", "pyttsx3_voice": "zh"},
        "male": {"sherpa_sid": 1, "espeak_voice": "zh+m1", "pyttsx3_voice": "zh+m1"},
        "child": {"sherpa_sid": 2, "espeak_voice": "zh+f2", "pyttsx3_voice": "zh+f2"},
    }

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        sherpa_model: Optional[str] = None,
        gender: str = "female",
    ) -> None:
        self._voice = voice
        self._rate = rate
        self._volume = volume
        self._sherpa_model = sherpa_model
        self._gender = gender.lower() if gender.lower() in self.GENDER_MAP else "female"
        self._voice_map = self.GENDER_MAP[self._gender]

        self._engines = {}
        self._current_engine = None
        self._current_name = ""
        self._preferred_engine = ""  # 记住首选引擎，fallback时不永久切换
        self._preferred_retry_counter = 0  # 首选引擎重探测计数器
        self._preferred_fail_count = 0  # 首选引擎连续失败次数
        self._sample_rate = 24000
        self._tested = False
        self._mode = "auto"

    # 每合成 10 次重新探测一次首选引擎（防止临时故障导致永久降级）
    PREFERRED_RETRY_INTERVAL = 10

    @property
    def name(self) -> str:
        return "auto_tts"

    def _build_engines(self) -> None:
        """构建引擎池"""
        self._engines = {
            "edge_tts": EdgeTTSTTS(voice=self._voice, rate=self._rate, volume=self._volume),
            "sherpa_onnx_tts": SherpaOnnxTTS(
                model_path=self._sherpa_model,
                voice_id=self._voice_map["sherpa_sid"],
            ),
            "pyttsx3_tts": Pyttsx3TTS(),
            "espeak_ng_tts": EspeakNGTTS(voice=self._voice_map["espeak_voice"]),
            "mock_tts": MockTTS(),
        }

    def set_mode(self, mode: str) -> None:
        """设置引擎选择模式"""
        self._mode = mode.lower()
        self._tested = False
        self._current_engine = None

    def _select_engine(self) -> bool:
        """测试并选择第一个可用的引擎"""
        if self._tested and self._current_engine:
            return True

        self._tested = True
        self._build_engines()

        if self._mode == "edge":
            return self._try_engine("edge_tts", "online neural")
        elif self._mode == "sherpa_onnx":
            return self._try_engine("sherpa_onnx_tts", "offline neural")
        elif self._mode == "pyttsx3":
            return self._try_engine("pyttsx3_tts", "system TTS")
        elif self._mode == "espeak":
            return self._try_engine("espeak_ng_tts", "synth fallback")

        # auto mode: offline only, prefer high-quality neural voice
        # Priority: sherpa-onnx (offline neural) > espeak-ng (offline synth) > pyttsx3 > mock
        order = ["sherpa_onnx_tts", "espeak_ng_tts", "pyttsx3_tts", "mock_tts"]
        for name in order:
            desc = {
                "sherpa_onnx_tts": "offline neural",
                "espeak_ng_tts": "offline synth",
                "pyttsx3_tts": "system TTS",
                "mock_tts": "beep only",
            }[name]
            if self._try_engine(name, desc):
                return True

        return False

    def _try_engine(self, name: str, desc: str) -> bool:
        """尝试单个引擎，返回是否成功"""
        engine = self._engines.get(name)
        if not engine:
            return False

        try:
            if name == "sherpa_onnx_tts":
                if not engine._check_available() or not engine._init_engine():
                    logger.info(f"TTS '{name}': not available")
                    return False
                logger.info(f"TTS '{name}': available ({desc})")
                self._current_engine = engine
                self._current_name = name
                return True

            elif name == "pyttsx3_tts":
                if not engine._check_available() or not engine._init_engine():
                    logger.info(f"TTS '{name}': not installed")
                    return False
                # Pre-check: test save_to_file actually works
                try:
                    test_audio = engine.synthesize("预检")
                    if len(test_audio) > 100:
                        logger.info(f"TTS '{name}': available ({desc})")
                        self._current_engine = engine
                        self._current_name = name
                        return True
                    else:
                        logger.info(f"TTS '{name}': synthesis returned empty audio")
                        return False
                except Exception as e:
                    logger.info(f"TTS '{name}': save_to_file broken on this system ({e})")
                    return False

            elif name == "espeak_ng_tts":
                if not engine._check_available():
                    logger.info(f"TTS '{name}': not installed")
                    return False
                logger.info(f"TTS '{name}': available ({desc})")
                self._current_engine = engine
                self._current_name = name
                return True

            elif name == "edge_tts":
                if not engine._check_available():
                    logger.info(f"TTS '{name}': not installed")
                    return False
                logger.info(f"TTS '{name}': available ({desc})")
                self._current_engine = engine
                self._current_name = name
                return True

            elif name == "mock_tts":
                logger.warning("All TTS engines unavailable, using mock (beep only)")
                self._current_engine = engine
                self._current_name = name
                return True

        except Exception as e:
            logger.warning(f"TTS '{name}' check failed: {e}")
            return False

        return False

    def synthesize(self, text: str) -> np.ndarray:
        if not self._select_engine():
            mock = MockTTS()
            self._sample_rate = mock.get_sample_rate()
            return mock.synthesize(text)

        # Remember preferred engine on first successful synthesis
        if not self._preferred_engine and self._current_name:
            self._preferred_engine = self._current_name

        # 周期性地重新探测首选引擎（每 RETRY_INTERVAL 次）
        if self._preferred_engine and self._current_name != self._preferred_engine:
            self._preferred_retry_counter += 1
            if self._preferred_retry_counter >= self.PREFERRED_RETRY_INTERVAL:
                self._preferred_retry_counter = 0
                if self._try_engine(self._preferred_engine, "retry preferred"):
                    logger.info(f"TTS recovered to preferred engine: {self._preferred_engine}")

        try:
            audio = self._current_engine.synthesize(text)
            self._sample_rate = self._current_engine.get_sample_rate()
            # 成功则重置失败计数
            self._preferred_fail_count = 0
            return audio
        except Exception as e:
            logger.warning(f"TTS '{self._current_name}' failed: {e}, trying fallback...")
            # 标记首选失败次数
            if self._current_name == self._preferred_engine:
                self._preferred_fail_count += 1

            # Try remaining engines in priority order (offline only)
            # But DON'T permanently switch - keep preferred engine for next call
            fallback_order = ["sherpa_onnx_tts", "espeak_ng_tts", "pyttsx3_tts", "mock_tts"]
            for name in fallback_order:
                if name == self._current_name:
                    continue
                if name == self._preferred_engine:
                    continue  # Skip if preferred already failed this round
                engine = self._engines.get(name)
                if not engine:
                    continue
                try:
                    if name == "sherpa_onnx_tts" and not engine._init_engine():
                        continue
                    if name == "pyttsx3_tts" and not engine._check_available():
                        continue
                    if name == "espeak_ng_tts" and not engine._check_available():
                        continue

                    audio = engine.synthesize(text)
                    # DON'T update self._current_engine - keep preferred for next call
                    self._sample_rate = engine.get_sample_rate()
                    logger.info(f"One-time fallback to TTS: {name} (will retry preferred next)")
                    return audio
                except Exception as e2:
                    logger.warning(f"Fallback '{name}' failed: {e2}")
                    continue

            logger.error("All TTS engines failed, using mock")
            mock = MockTTS()
            self._sample_rate = mock.get_sample_rate()
            return mock.synthesize(text)

    def get_sample_rate(self) -> int:
        return self._sample_rate

    @property
    def current_engine_name(self) -> str:
        return self._current_name

    def execute(self, *args, **kwargs):
        return self.synthesize(*args, **kwargs)
