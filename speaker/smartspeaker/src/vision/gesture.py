from __future__ import annotations
import time
import numpy as np
from typing import Optional, Tuple, Dict
from dataclasses import dataclass
from ..utils.logger import logger


@dataclass
class HandLandmark:
    x: float
    y: float
    z: float


@dataclass
class GestureResult:
    gesture_type: str
    confidence: float
    position: Tuple[int, int]
    timestamp: float


class GestureRecognizer:
    GESTURE_TYPES = {
        "palm": "手掌张开",
        "fist": "握拳",
        "thumb_up": "点赞",
        "index_point": "食指指向",
        "victory": "胜利手势",
        "wave_left": "向左挥手",
        "wave_right": "向右挥手",
        "unknown": "未知手势",
    }

    def __init__(self, camera_index: int = 0):
        self._camera_index = camera_index
        self._cap = None
        self._mp_hands = None
        self._mp_drawing = None
        self._hands = None
        self._initialized = False
        self._last_gesture: Optional[GestureResult] = None
        self._last_hand_positions = []
        self._hand_detected = False

    def _init_mediapipe(self) -> bool:
        if self._initialized:
            return True

        try:
            import mediapipe as mp
            self._mp_hands = mp.solutions.hands
            self._mp_drawing = mp.solutions.drawing_utils

            self._hands = self._mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )

            self._initialized = True
            logger.info("MediaPipe Hands initialized")
            return True

        except ImportError:
            logger.warning("mediapipe not installed, using mock mode")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize MediaPipe: {e}")
            return False

    def _init_camera(self) -> bool:
        try:
            import cv2

            if self._cap is None:
                self._cap = cv2.VideoCapture(self._camera_index)
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self._cap.set(cv2.CAP_PROP_FPS, 30)

            if not self._cap.isOpened():
                logger.warning(f"Failed to open camera {self._camera_index}, trying next")
                self._cap.release()
                self._cap = cv2.VideoCapture(self._camera_index + 1)

            return self._cap.isOpened()

        except Exception as e:
            logger.error(f"Camera initialization error: {e}")
            return False

    def _is_finger_extended(self, landmarks, finger_tip_idx, finger_pip_idx) -> bool:
        tip = landmarks[finger_tip_idx]
        pip = landmarks[finger_pip_idx]
        return tip.y < pip.y

    def _is_thumb_extended(self, landmarks) -> bool:
        thumb_tip = landmarks[4]
        thumb_ip = landmarks[3]
        index_mcp = landmarks[5]
        return abs(thumb_tip.x - index_mcp.x) > 0.1

    def _classify_gesture(self, landmarks) -> Tuple[str, float]:
        fingers = {
            "thumb": self._is_thumb_extended(landmarks),
            "index": self._is_finger_extended(landmarks, 8, 6),
            "middle": self._is_finger_extended(landmarks, 12, 10),
            "ring": self._is_finger_extended(landmarks, 16, 14),
            "pinky": self._is_finger_extended(landmarks, 20, 18),
        }

        extended_count = sum(fingers.values())

        if extended_count == 0:
            return "fist", 0.95
        elif extended_count == 5:
            return "palm", 0.90
        elif extended_count == 1 and fingers["thumb"]:
            return "thumb_up", 0.85
        elif extended_count == 1 and fingers["index"]:
            return "index_point", 0.85
        elif extended_count == 2 and fingers["index"] and fingers["middle"]:
            return "victory", 0.90
        else:
            return "unknown", 0.50

    def _detect_wave(self, current_x: float) -> Optional[str]:
        self._last_hand_positions.append(current_x)

        if len(self._last_hand_positions) > 10:
            self._last_hand_positions.pop(0)

        if len(self._last_hand_positions) < 5:
            return None

        diffs = []
        for i in range(1, len(self._last_hand_positions)):
            diffs.append(self._last_hand_positions[i] - self._last_hand_positions[i - 1])

        total_movement = sum(abs(d) for d in diffs)

        if total_movement > 0.3:
            net_movement = sum(diffs)
            if net_movement > 0.15:
                self._last_hand_positions = []
                return "wave_right"
            elif net_movement < -0.15:
                self._last_hand_positions = []
                return "wave_left"

        return None

    def process_frame(self, frame: Optional[np.ndarray] = None) -> Optional[GestureResult]:
        if not self._init_mediapipe():
            return self._mock_detection(frame)

        if frame is None:
            if not self._init_camera():
                return self._mock_detection(frame)

            try:
                import cv2

                ret, frame = self._cap.read()
                if not ret:
                    return self._mock_detection(frame)
            except Exception as e:
                logger.error(f"Frame capture error: {e}")
                return self._mock_detection(frame)

        try:
            import cv2

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            results = self._hands.process(frame_rgb)

            if results.multi_hand_landmarks:
                self._hand_detected = True

                for hand_landmarks in results.multi_hand_landmarks:
                    landmarks = hand_landmarks.landmark

                    wrist_x = landmarks[0].x
                    wrist_y = landmarks[0].y

                    position_x = int(wrist_x * frame.shape[1])
                    position_y = int(wrist_y * frame.shape[0])

                    gesture_type, confidence = self._classify_gesture(landmarks)

                    if gesture_type == "palm":
                        wave_gesture = self._detect_wave(wrist_x)
                        if wave_gesture:
                            gesture_type = wave_gesture
                            confidence = 0.80

                    result = GestureResult(
                        gesture_type=gesture_type,
                        confidence=confidence,
                        position=(position_x, position_y),
                        timestamp=time.time(),
                    )
                    self._last_gesture = result

                    return result

            else:
                self._hand_detected = False

        except Exception as e:
            logger.error(f"Gesture recognition error: {e}")

        return None

    def _mock_detection(self, frame: Optional[np.ndarray]) -> Optional[GestureResult]:
        height, width = (480, 640) if frame is None else frame.shape[:2]

        center_x = width // 2 + int(np.sin(time.time() * 2) * 80)
        center_y = height // 2 + int(np.cos(time.time() * 1.5) * 40)

        gestures = ["palm", "fist", "thumb_up", "index_point", "victory", "wave_left", "wave_right"]
        gesture_type = gestures[int(time.time() * 0.5) % len(gestures)]
        confidence = 0.7 + 0.3 * abs(np.sin(time.time() * 3))

        result = GestureResult(
            gesture_type=gesture_type,
            confidence=confidence,
            position=(center_x, center_y),
            timestamp=time.time(),
        )
        self._last_gesture = result

        return result

    def draw_landmarks(self, frame: np.ndarray) -> np.ndarray:
        if not self._initialized or self._last_gesture is None:
            return frame

        try:
            import cv2

            if not self._hand_detected:
                return frame

            results = self._hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

            if results.multi_hand_landmarks:
                for hand_landmarks in results.multi_hand_landmarks:
                    self._mp_drawing.draw_landmarks(
                        frame,
                        hand_landmarks,
                        self._mp_hands.HAND_CONNECTIONS,
                        self._mp_drawing.DrawingSpec(
                            color=(0, 255, 0), thickness=2, circle_radius=2
                        ),
                        self._mp_drawing.DrawingSpec(
                            color=(0, 0, 255), thickness=2, circle_radius=1
                        ),
                    )

                cv2.putText(
                    frame,
                    f"Gesture: {self.GESTURE_TYPES.get(self._last_gesture.gesture_type, self._last_gesture.gesture_type)}",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )

        except Exception as e:
            logger.error(f"Drawing error: {e}")

        return frame

    def release(self):
        if self._cap:
            self._cap.release()
            self._cap = None
        if self._hands:
            self._hands.close()
            self._hands = None
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def last_gesture(self) -> Optional[GestureResult]:
        return self._last_gesture

    @property
    def hand_detected(self) -> bool:
        return self._hand_detected