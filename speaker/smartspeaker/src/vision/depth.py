from __future__ import annotations
import time
import numpy as np
from typing import Optional, Tuple, List
from dataclasses import dataclass
from ..utils.logger import logger

from ..core.message_bus import MessageBus, Event, EventType
from ..config import VisionConfig


@dataclass
class DepthResult:
    distance: float
    confidence: float
    point_x: int
    point_y: int
    timestamp: float


@dataclass
class GestureResult:
    gesture_type: str
    confidence: float
    position: Tuple[int, int]
    timestamp: float


class VisionDepth:
    def __init__(self, config: VisionConfig, bus: MessageBus) -> None:
        self._config = config
        self._bus = bus
        self._running = False
        self._frame_count = 0
        self._last_depth: Optional[DepthResult] = None
        self._last_gesture: Optional[GestureResult] = None

        self._left_camera = None
        self._right_camera = None
        self._stereo_matcher = None
        self._cv2_initialized = False

        self._gesture_recognizer = None

        self._subscribe_events()
        logger.info("VisionDepth initialized")

    def _subscribe_events(self) -> None:
        self._bus.subscribe(
            EventType.SYSTEM_STATUS, self._on_system_status, "vision_depth"
        )

    def _on_system_status(self, event: Event) -> None:
        status = event.data.get("status")
        if status == "shutdown":
            self.stop()

    def _init_cv2(self) -> bool:
        if self._cv2_initialized:
            return True
        
        try:
            import cv2
            self._cv2_initialized = True
            return True
        except ImportError:
            logger.warning("opencv-python not installed, using mock mode")
            return False

    def _init_stereo_matcher(self) -> None:
        if not self._init_cv2():
            return
        
        try:
            import cv2
            
            self._stereo_matcher = cv2.StereoSGBM_create(
                minDisparity=0,
                numDisparities=160,
                blockSize=9,
                P1=8 * 3 * 9 ** 2,
                P2=32 * 3 * 9 ** 2,
                disp12MaxDiff=1,
                uniquenessRatio=10,
                speckleWindowSize=100,
                speckleRange=2,
                preFilterCap=63,
                mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
            )
            logger.info("StereoSGBM matcher initialized")
        except Exception as e:
            logger.error(f"Failed to initialize StereoSGBM: {e}")

    def captureStereo(self) -> Tuple[np.ndarray, np.ndarray]:
        if not self._init_cv2():
            width = self._config.camera_width
            height = self._config.camera_height
            left_frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
            right_frame = np.roll(left_frame, shift=5, axis=1)
            return left_frame, right_frame

        try:
            import cv2
            
            if self._left_camera is None:
                self._left_camera = cv2.VideoCapture(self._config.camera_index)
                self._left_camera.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.camera_width)
                self._left_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.camera_height)
                self._left_camera.set(cv2.CAP_PROP_FPS, self._config.camera_fps)
            
            if self._right_camera is None:
                self._right_camera = cv2.VideoCapture(self._config.camera_index + 1)
                self._right_camera.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.camera_width)
                self._right_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.camera_height)
                self._right_camera.set(cv2.CAP_PROP_FPS, self._config.camera_fps)

            ret_left, left_frame = self._left_camera.read()
            ret_right, right_frame = self._right_camera.read()

            if not ret_left or not ret_right:
                logger.warning("Failed to capture stereo frames, using mock data")
                width = self._config.camera_width
                height = self._config.camera_height
                left_frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
                right_frame = np.roll(left_frame, shift=5, axis=1)

        except Exception as e:
            logger.error(f"Camera capture error: {e}")
            width = self._config.camera_width
            height = self._config.camera_height
            left_frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
            right_frame = np.roll(left_frame, shift=5, axis=1)

        self._frame_count += 1
        self._bus.publish(
            Event(
                event_type=EventType.VISION_FRAME,
                data={
                    "frame_id": self._frame_count,
                    "width": left_frame.shape[1],
                    "height": left_frame.shape[0],
                    "timestamp": time.time(),
                },
                source="VisionDepth",
            )
        )
        return left_frame, right_frame

    def computeDisparity(
        self, left_frame: np.ndarray, right_frame: np.ndarray
    ) -> np.ndarray:
        if self._stereo_matcher is None:
            self._init_stereo_matcher()

        if self._stereo_matcher is not None:
            try:
                import cv2
                
                left_gray = cv2.cvtColor(left_frame, cv2.COLOR_BGR2GRAY)
                right_gray = cv2.cvtColor(right_frame, cv2.COLOR_BGR2GRAY)

                disparity = self._stereo_matcher.compute(left_gray, right_gray).astype(np.float32) / 16.0
                
                disparity = cv2.normalize(disparity, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                
                return disparity.astype(np.float32)
            except Exception as e:
                logger.error(f"StereoSGBM error: {e}")

        height, width = left_frame.shape[:2]
        left_gray = np.mean(left_frame, axis=2)
        right_gray = np.mean(right_frame, axis=2)

        disparity = np.zeros((height, width), dtype=np.float32)
        max_disparity = 64
        block_size = 9
        half_block = block_size // 2

        for y in range(half_block, height - half_block, 4):
            for x in range(half_block + max_disparity, width - half_block, 4):
                left_block = left_gray[
                    y - half_block : y + half_block + 1,
                    x - half_block : x + half_block + 1,
                ]
                best_disp = 0
                best_cost = float("inf")
                for d in range(max_disparity):
                    xr = x - d
                    if xr - half_block < 0:
                        break
                    right_block = right_gray[
                        y - half_block : y + half_block + 1,
                        xr - half_block : xr + half_block + 1,
                    ]
                    cost = np.sum(np.abs(left_block - right_block))
                    if cost < best_cost:
                        best_cost = cost
                        best_disp = d
                disparity[y, x] = best_disp

        return disparity

    def estimateDepth(self, disparity: np.ndarray) -> DepthResult:
        focal = self._config.focal_length
        baseline = self._config.stereo_baseline

        center_y = disparity.shape[0] // 2
        center_x = disparity.shape[1] // 2
        
        window_size = 10
        y_min = max(0, center_y - window_size)
        y_max = min(disparity.shape[0], center_y + window_size + 1)
        x_min = max(0, center_x - window_size)
        x_max = min(disparity.shape[1], center_x + window_size + 1)
        
        center_disp = np.mean(disparity[y_min:y_max, x_min:x_max])

        if center_disp <= 0:
            center_disp = 1.0

        distance = (focal * baseline) / center_disp
        distance = max(
            self._config.min_detection_distance,
            min(distance, self._config.max_detection_distance),
        )

        confidence = min(1.0, center_disp / 32.0)

        result = DepthResult(
            distance=distance,
            confidence=confidence,
            point_x=center_x,
            point_y=center_y,
            timestamp=time.time(),
        )
        self._last_depth = result

        self._bus.publish(
            Event(
                event_type=EventType.DISTANCE_UPDATE,
                data={
                    "distance": result.distance,
                    "confidence": result.confidence,
                    "timestamp": result.timestamp,
                },
                source="VisionDepth",
            )
        )

        return result

    def trackTarget(self, frame: np.ndarray) -> Optional[GestureResult]:
        if not self._config.gesture_enabled:
            return None

        if self._gesture_recognizer is None:
            try:
                from .gesture import GestureRecognizer
                self._gesture_recognizer = GestureRecognizer()
            except ImportError:
                logger.warning("GestureRecognizer import failed, using mock")

        if self._gesture_recognizer and self._gesture_recognizer.is_initialized:
            result = self._gesture_recognizer.process_frame(frame)
            if result and result.confidence > 0.7:
                self._last_gesture = result
                self._bus.publish(
                    Event(
                        event_type=EventType.GESTURE_DETECTED,
                        data={
                            "gesture": result.gesture_type,
                            "confidence": result.confidence,
                            "position": result.position,
                            "timestamp": result.timestamp,
                        },
                        source="VisionDepth",
                        priority=4,
                    )
                )
                logger.debug(f"Gesture detected: {result.gesture_type} (conf={result.confidence:.2f})")
            return result
        else:
            return self._mock_gesture_detection(frame)

    def _mock_gesture_detection(self, frame: np.ndarray) -> Optional[GestureResult]:
        height, width = frame.shape[:2]
        center_x = width // 2 + int(np.sin(time.time() * 2) * 50)
        center_y = height // 2 + int(np.cos(time.time() * 1.5) * 30)
        gestures = ["palm", "fist", "thumb_up", "index_point", "victory", "wave_left", "wave_right"]
        gesture_type = gestures[int(time.time()) % len(gestures)]
        confidence = 0.7 + 0.3 * abs(np.sin(time.time() * 3))

        result = GestureResult(
            gesture_type=gesture_type,
            confidence=confidence,
            position=(center_x, center_y),
            timestamp=time.time(),
        )
        self._last_gesture = result

        if confidence > 0.8:
            self._bus.publish(
                Event(
                    event_type=EventType.GESTURE_DETECTED,
                    data={
                        "gesture": gesture_type,
                        "confidence": confidence,
                        "position": (center_x, center_y),
                        "timestamp": result.timestamp,
                    },
                    source="VisionDepth",
                    priority=4,
                )
            )
            logger.debug(f"Gesture detected (mock): {gesture_type} (conf={confidence:.2f})")

        return result

    def process_frame(self) -> Optional[DepthResult]:
        if not self._running:
            return None

        left, right = self.captureStereo()
        disparity = self.computeDisparity(left, right)
        depth = self.estimateDepth(disparity)
        self.trackTarget(left)

        return depth

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._frame_count = 0
        self._init_stereo_matcher()
        logger.info("VisionDepth started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        
        if self._left_camera:
            self._left_camera.release()
            self._left_camera = None
        
        if self._right_camera:
            self._right_camera.release()
            self._right_camera = None
        
        if self._gesture_recognizer:
            self._gesture_recognizer.release()
            self._gesture_recognizer = None
        
        logger.info("VisionDepth stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_depth(self) -> Optional[DepthResult]:
        return self._last_depth

    @property
    def last_gesture(self) -> Optional[GestureResult]:
        return self._last_gesture

    @property
    def frame_count(self) -> int:
        return self._frame_count
