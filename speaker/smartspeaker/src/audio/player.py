from __future__ import annotations
import os
import sys
import re
import platform
import tempfile
import subprocess
import numpy as np
from typing import Optional
from abc import ABC, abstractmethod
from ..utils.logger import logger


def _normalize_name(name: str) -> str:
    """归一化设备名：去标点、空格、特殊字符，转小写。用于名称模糊匹配"""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (name or "").lower())


def _find_alsa_plughw_by_name(target_name: str) -> Optional[str]:
    """通过 aplay -l 解析出匹配设备名的 plughw:X,Y"""
    if platform.system() != "Linux":
        return None
    target_norm = _normalize_name(target_name)
    if not target_norm:
        return None
    try:
        result = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0:
            return None
        # 匹配 card X: ... device Y: ...
        for line in result.stdout.splitlines():
            m = re.search(r"card (\d+):[^\[]*\[([^\]]*)\].*device (\d+):", line)
            if not m:
                continue
            card = m.group(1)
            card_label = m.group(2)
            dev = m.group(3)
            if target_norm in _normalize_name(card_label):
                return f"plughw:{card},{dev}"
    except Exception as e:
        logger.debug(f"aplay -l parse failed: {e}")
    return None


class AudioBackend(ABC):
    @abstractmethod
    def play(self, audio_data: np.ndarray, sample_rate: int) -> bool:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


class SoundDeviceBackend(AudioBackend):
    def __init__(self, output_device: Optional[int] = None):
        self._output_device = output_device
        self._sd_module = None
        self._initialized = False
        self._actual_sample_rate = 44100

    @property
    def name(self) -> str:
        return "sounddevice"

    def is_available(self) -> bool:
        if self._initialized:
            return True
        try:
            import sounddevice as sd
            self._sd_module = sd

            if self._output_device is not None:
                try:
                    device_info = sd.query_devices(self._output_device)
                    self._actual_sample_rate = int(device_info['default_samplerate'])
                except Exception as e:
                    logger.warning(f"Requested output device {self._output_device} invalid: {e}, using default")
                    self._output_device = None

            if self._output_device is None:
                default_out = sd.default.device["output"]
                if default_out is None:
                    logger.warning("No default output device found for sounddevice")
                    return False
                self._output_device = default_out
                device_info = sd.query_devices(self._output_device)
                self._actual_sample_rate = int(device_info['default_samplerate'])

            self._initialized = True
            logger.info(f"SoundDevice backend available: device={self._output_device}, sr={self._actual_sample_rate}")
            return True
        except ImportError:
            logger.info("SoundDevice backend not available (sounddevice not installed)")
            return False
        except Exception as e:
            logger.warning(f"SoundDevice backend init failed: {e}")
            return False

    def _resample(self, data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        if src_rate == dst_rate:
            return data
        try:
            from scipy.signal import resample
            num_samples = int(len(data) * dst_rate / src_rate)
            return resample(data, num_samples).astype(np.float32)
        except ImportError:
            ratio = dst_rate / src_rate
            indices = np.arange(int(len(data) * ratio)) / ratio
            indices = np.clip(indices.astype(int), 0, len(data) - 1)
            return data[indices].astype(np.float32)

    def play(self, audio_data: np.ndarray, sample_rate: int) -> bool:
        if not self.is_available():
            return False

        try:
            data = audio_data.astype(np.float32)

            if len(data.shape) > 1:
                data = np.mean(data, axis=1)

            max_val = np.max(np.abs(data))
            if max_val > 1.0:
                data = data / max_val

            if sample_rate != self._actual_sample_rate:
                data = self._resample(data, sample_rate, self._actual_sample_rate)

            # Only pass device if explicitly set; let PortAudio use default otherwise
            play_kwargs = {"blocking": False}
            if self._output_device is not None:
                play_kwargs["device"] = self._output_device

            self._sd_module.play(data, self._actual_sample_rate, **play_kwargs)
            self._sd_module.wait()
            return True
        except Exception as e:
            logger.error(f"SoundDevice playback error: {e}")
            return False

    def stop(self) -> None:
        if self._sd_module:
            try:
                self._sd_module.stop()
            except Exception:
                pass


class AlsaBackend(AudioBackend):
    def __init__(self, device: Optional[str] = None):
        self._device = device
        self._aplay_available = None
        self._process = None
        self._tested_devices: list[str] = []
        self._use_scipy = None

    @property
    def name(self) -> str:
        return "alsa"

    def is_available(self) -> bool:
        if self._aplay_available is not None:
            return self._aplay_available

        if platform.system() != "Linux":
            self._aplay_available = False
            return False

        try:
            result = subprocess.run(
                ["aplay", "--version"],
                capture_output=True, text=True, timeout=2
            )
            self._aplay_available = result.returncode == 0
            if self._aplay_available:
                logger.info(f"ALSA backend available: {result.stdout.strip()}")
            return self._aplay_available
        except Exception:
            self._aplay_available = False
            return False

    def _discover_devices(self) -> list[str]:
        """自动探测可用的 ALSA PCM 设备"""
        if self._tested_devices:
            return self._tested_devices

        candidates = []
        if self._device:
            candidates.append(self._device)
        candidates.extend(["default", "plughw:0,0", "hw:0,0", "plughw:1,0", "hw:1,0"])

        try:
            result = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                import re
                for line in result.stdout.splitlines():
                    m = re.search(r"card (\d+): .*device (\d+):", line)
                    if m:
                        card, dev = m.group(1), m.group(2)
                        for prefix in ["plughw", "hw"]:
                            name = f"{prefix}:{card},{dev}"
                            if name not in candidates:
                                candidates.append(name)
        except Exception:
            pass

        self._tested_devices = candidates
        return candidates

    def _try_play(self, device: str, temp_path: str) -> bool:
        """尝试用指定设备播放"""
        try:
            cmd = ["aplay", "-q", "-D", device, temp_path]
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            _, stderr = self._process.communicate(timeout=30)
            rc = self._process.returncode
            self._process = None
            if rc == 0:
                return True
            err = stderr.decode("utf-8", errors="ignore").strip()[:120] if stderr else ""
            logger.debug(f"ALSA device '{device}' failed: {err}")
            return False
        except subprocess.TimeoutExpired:
            logger.warning(f"ALSA device '{device}' timed out")
            if self._process:
                self._process.kill()
                self._process = None
            return False
        except Exception as e:
            logger.debug(f"ALSA device '{device}' error: {e}")
            return False

    def play(self, audio_data: np.ndarray, sample_rate: int) -> bool:
        if not self.is_available():
            return False

        try:
            data = audio_data.astype(np.float32)

            if len(data.shape) > 1:
                data = np.mean(data, axis=1)

            max_val = np.max(np.abs(data))
            if max_val > 1.0:
                data = data / max_val

            pcm_data = (data * 32767).astype(np.int16)

            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            data_dir = os.path.join(project_root, "data")
            os.makedirs(data_dir, exist_ok=True)
            temp_path = os.path.join(data_dir, "tts_temp.wav")

            try:
                if self._use_scipy is None:
                    try:
                        import scipy.io.wavfile
                        self._use_scipy = True
                    except ImportError:
                        self._use_scipy = False

                if self._use_scipy:
                    import scipy.io.wavfile
                    scipy.io.wavfile.write(temp_path, sample_rate, pcm_data)
                else:
                    import wave
                    with wave.open(temp_path, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
                        wf.writeframes(pcm_data.tobytes())

                devices = self._discover_devices()
                for device in devices:
                    logger.debug(f"ALSA trying device: {device}")
                    if self._try_play(device, temp_path):
                        logger.info(f"ALSA playback success on device: {device}")
                        self._device = device
                        return True

                logger.error("ALSA: all devices failed")
                return False
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        except Exception as e:
            logger.error(f"ALSA playback error: {e}")
            return False

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None


class PulseAudioBackend(AudioBackend):
    def __init__(self, device: str = ""):
        self._device = device
        self._paplay_available = None
        self._process = None

    @property
    def name(self) -> str:
        return "pulseaudio"

    def is_available(self) -> bool:
        if self._paplay_available is not None:
            return self._paplay_available

        if platform.system() != "Linux":
            self._paplay_available = False
            return False

        try:
            result = subprocess.run(
                ["paplay", "--version"],
                capture_output=True, text=True, timeout=2
            )
            self._paplay_available = result.returncode == 0
            if self._paplay_available:
                logger.info(f"PulseAudio backend available")
            return self._paplay_available
        except Exception:
            self._paplay_available = False
            return False

    def play(self, audio_data: np.ndarray, sample_rate: int) -> bool:
        if not self.is_available():
            return False

        try:
            data = audio_data.astype(np.float32)

            if len(data.shape) > 1:
                data = np.mean(data, axis=1)

            max_val = np.max(np.abs(data))
            if max_val > 1.0:
                data = data / max_val

            pcm_data = (data * 32767).astype(np.int16)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name

            try:
                import wave
                with wave.open(temp_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(pcm_data.tobytes())

                cmd = ["paplay", temp_path]
                if self._device:
                    cmd.extend(["--device", self._device])

                self._process = subprocess.Popen(cmd)
                self._process.wait(timeout=300)
                self._process = None
                return True
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        except Exception as e:
            logger.error(f"PulseAudio playback error: {e}")
            return False

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None


class WinMMBackend(AudioBackend):
    def __init__(self):
        self._winsound_available = None

    @property
    def name(self) -> str:
        return "winmm"

    def is_available(self) -> bool:
        if self._winsound_available is not None:
            return self._winsound_available

        if platform.system() != "Windows":
            self._winsound_available = False
            return False

        try:
            import winsound  # noqa: F401
            self._winsound_available = True
            logger.info("WinMM backend available")
            return True
        except ImportError:
            self._winsound_available = False
            return False

    def play(self, audio_data: np.ndarray, sample_rate: int) -> bool:
        if not self.is_available():
            return False

        try:
            import winsound
            import wave

            data = audio_data.astype(np.float32)

            if len(data.shape) > 1:
                data = np.mean(data, axis=1)

            max_val = np.max(np.abs(data))
            if max_val > 1.0:
                data = data / max_val

            pcm_data = (data * 32767).astype(np.int16)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name

            try:
                with wave.open(temp_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(pcm_data.tobytes())

                winsound.PlaySound(temp_path, winsound.SND_FILENAME)
                return True
            finally:
                winsound.PlaySound(None, winsound.SND_PURGE)
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        except Exception as e:
            logger.error(f"WinMM playback error: {e}")
            return False

    def stop(self) -> None:
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass


class AudioPlayer:
    def __init__(self, sample_rate: int = 44100, output_device: Optional[int] = None) -> None:
        self._sample_rate = sample_rate
        self._output_device = output_device
        self._playing = False
        self._backends: list[AudioBackend] = []
        self._current_backend: Optional[AudioBackend] = None
        self._initialized = False
        self._alsa_device_name: Optional[str] = None  # 解析后的 ALSA 设备名

    def _resolve_alsa_device(self) -> Optional[str]:
        """根据配置的 output_device 解析为 ALSA plughw:X,Y 设备名"""
        if self._output_device is None:
            return None
        # 已是字符串设备名（"plughw:0,0" / "hw:1,0" / "default"）则原样返回
        if isinstance(self._output_device, str):
            return self._output_device
        # 整数索引：通过 sounddevice 查到 card/dev，再映射
        try:
            import sounddevice as sd
            info = sd.query_devices(self._output_device)
            name = (info.get("name") or "").lower()
            hostapi = info.get("hostapi", 0)
            # ALSA hostapi 索引通常为 0
            if hostapi == 0 and platform.system() == "Linux":
                # sounddevice 没有直接暴露 card，需要从 aplay -l 找
                plughw = _find_alsa_plughw_by_name(name)
                if plughw:
                    logger.info(f"Resolved output device {self._output_device} ('{info.get('name')}') -> {plughw}")
                    return plughw
            # 兜底：fallback 到 default
            return "default"
        except Exception as e:
            logger.debug(f"Resolve ALSA device failed: {e}")
            return "default"

    def _init_backends(self) -> None:
        if self._initialized:
            return

        self._initialized = True
        backends: list[AudioBackend] = []

        if platform.system() == "Linux":
            alsa_name = self._resolve_alsa_device()
            self._alsa_device_name = alsa_name
            backends.append(AlsaBackend(alsa_name))
            backends.append(SoundDeviceBackend(self._output_device))
            backends.append(PulseAudioBackend())
        elif platform.system() == "Windows":
            backends.append(SoundDeviceBackend(self._output_device))
            backends.append(WinMMBackend())
        else:
            backends.append(SoundDeviceBackend(self._output_device))

        for backend in backends:
            if backend.is_available():
                self._backends.append(backend)

        if self._backends:
            self._current_backend = self._backends[0]
            logger.info(f"AudioPlayer initialized with {len(self._backends)} backends, primary: {self._current_backend.name}")
        else:
            logger.warning("No audio backends available!")

    def play(self, audio_data: np.ndarray, sample_rate: Optional[int] = None) -> None:
        self._init_backends()

        if not self._backends:
            logger.warning("No audio backends available, skipping playback")
            return

        sr = sample_rate or self._sample_rate

        if len(audio_data) == 0:
            logger.warning("Empty audio data, skipping play")
            return

        self._playing = True

        for backend in self._backends:
            try:
                logger.debug(f"Trying audio backend: {backend.name}")
                success = backend.play(audio_data, sr)
                if success:
                    self._current_backend = backend
                    self._playing = False
                    logger.debug(f"Playback successful with backend: {backend.name}")
                    return
                else:
                    logger.warning(f"Backend {backend.name} failed, trying next...")
            except Exception as e:
                logger.warning(f"Backend {backend.name} error: {e}, trying next...")

        self._playing = False
        logger.error("All audio backends failed")

    def play_chunk(self, audio_data: np.ndarray, sample_rate: Optional[int] = None) -> None:
        self.play(audio_data, sample_rate)

    def wait(self) -> None:
        while self._playing:
            import time
            time.sleep(0.05)

    def stop(self) -> None:
        self._playing = False
        for backend in self._backends:
            try:
                backend.stop()
            except Exception:
                pass
        logger.info("Audio stopped")

    def reset(self) -> None:
        self.stop()
        self._backends.clear()
        self._current_backend = None
        self._initialized = False
        logger.info("AudioPlayer reset")

    def set_sample_rate(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def current_backend(self) -> Optional[str]:
        return self._current_backend.name if self._current_backend else None

    @property
    def available_backends(self) -> list[str]:
        self._init_backends()
        return [b.name for b in self._backends]