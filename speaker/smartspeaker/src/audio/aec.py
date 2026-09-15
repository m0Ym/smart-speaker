from __future__ import annotations
import numpy as np
from typing import Optional
from ..utils.logger import logger


class AECProcessor:
    def __init__(self, sample_rate: int = 16000, frame_size: int = 160) -> None:
        self._sample_rate = sample_rate
        self._frame_size = frame_size
        self._aec = None
        self._enabled = True
        self._initialized = False
        self._warned = False

    def _init_aec(self) -> bool:
        if self._initialized:
            return True
        
        try:
            from speexdsp import EchoCanceller
            
            self._aec = EchoCanceller.create(
                sample_rate=self._sample_rate,
                frame_size=self._frame_size,
                filter_length_ms=200,
            )
            self._initialized = True
            logger.info(f"AEC initialized: {self._sample_rate}Hz, frame={self._frame_size}")
            return True
        except ImportError:
            if not self._warned:
                logger.warning("speexdsp not installed, AEC disabled")
                self._warned = True
            return False
        except Exception as e:
            if not self._warned:
                logger.error(f"Failed to initialize AEC: {e}")
                self._warned = True
            return False

    def process(self, input_data: np.ndarray, reference_data: np.ndarray = None) -> np.ndarray:
        if not self._enabled:
            return input_data
        
        if not self._init_aec():
            return input_data

        try:
            if reference_data is not None and len(reference_data) > 0:
                ref_data = reference_data.astype(np.float32)
                if len(ref_data) < self._frame_size:
                    ref_data = np.pad(ref_data, (0, self._frame_size - len(ref_data)))
                
                self._aec.process_reverse(ref_data[:self._frame_size])
            
            input_data = input_data.astype(np.float32)
            
            if len(input_data) < self._frame_size:
                input_data = np.pad(input_data, (0, self._frame_size - len(input_data)))
            
            output_data = self._aec.process(input_data[:self._frame_size])
            
            return output_data[:len(input_data)]
        except Exception as e:
            logger.error(f"AEC processing error: {e}")
            return input_data

    def reset(self) -> None:
        if self._aec:
            self._aec.reset()
            logger.info("AEC reset")

    def enable(self, enabled: bool) -> None:
        self._enabled = enabled
        logger.info(f"AEC {'enabled' if enabled else 'disabled'}")

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_enabled(self) -> bool:
        return self._enabled


class BargeInDetector:
    def __init__(self, sample_rate: int = 16000, threshold: float = 0.15) -> None:
        self._sample_rate = sample_rate
        self._threshold = threshold
        self._energy_history = []
        self._max_history = 30
        self._barge_in_detected = False
        self._enabled = True

    def detect(self, audio_data: np.ndarray) -> bool:
        if not self._enabled:
            return False
            
        energy = np.sqrt(np.mean(audio_data ** 2))
        
        self._energy_history.append(energy)
        if len(self._energy_history) > self._max_history:
            self._energy_history.pop(0)
        
        avg_energy = np.mean(self._energy_history) if self._energy_history else 0
        std_energy = np.std(self._energy_history) if len(self._energy_history) > 1 else 0
        
        if avg_energy > 0:
            z_score = (energy - avg_energy) / (std_energy + 1e-10)
        else:
            z_score = 0
        
        if energy > self._threshold and z_score > 2.0:
            self._barge_in_detected = True
            logger.debug(f"Barge-in detected: energy={energy:.4f}, z_score={z_score:.2f}, threshold={self._threshold}")
        else:
            self._barge_in_detected = False
        
        return self._barge_in_detected

    def enable(self, enabled: bool) -> None:
        self._enabled = enabled

    def reset(self) -> None:
        self._energy_history = []
        self._barge_in_detected = False

    @property
    def is_barge_in(self) -> bool:
        return self._barge_in_detected

    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self._threshold = value