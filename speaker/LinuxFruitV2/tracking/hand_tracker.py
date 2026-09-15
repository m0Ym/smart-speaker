import cv2
import mediapipe as mp
import time
import os
import threading

from config import SCREEN_WIDTH, SCREEN_HEIGHT, USE_GPU, POSE_MIN_DETECTION_CONFIDENCE, POSE_MIN_TRACKING_CONFIDENCE


def detect_gpu():
    try:
        nvidia_smi = os.popen('nvidia-smi').read()
        if 'NVIDIA' in nvidia_smi:
            return True, 'NVIDIA GPU detected'
    except:
        pass
    
    try:
        if cv2.cuda.getCudaEnabledDeviceCount() > 0:
            return True, f'OpenCV CUDA available: {cv2.cuda.getCudaEnabledDeviceCount()} devices'
    except:
        pass
    
    return False, 'No GPU detected, using CPU'


class RawHandData:
    def __init__(self):
        self.is_detected = False
        self.x = 0.0
        self.y = 0.0
        self.confidence = 0.0
        self.hand_type = 'unknown'
        self.timestamp = 0.0


class HandTracker:
    POSE_LANDMARKS = {
        'left_wrist': 15,
        'right_wrist': 16,
        'left_elbow': 13,
        'right_elbow': 14,
        'left_shoulder': 11,
        'right_shoulder': 12,
    }
    
    def __init__(self):
        self._mp_pose = mp.solutions.pose
        self._pose = None
        self._is_initialized = False
        self._gpu_available = False

        self._left_hand = RawHandData()
        self._right_hand = RawHandData()
        
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._result_lock = threading.Lock()
        self._detection_thread = None
        self._is_detecting = False
        
        self._last_frame_id = 0
        self._processed_frame_id = 0

        self.on_hand_updated = None
    
    def initialize(self):
        if self._is_initialized:
            return
        
        if USE_GPU:
            gpu_available, msg = detect_gpu()
            self._gpu_available = gpu_available
            print(f"GPU Detection: {msg}")
            
            os.environ['MEDIAPIPE_GPU'] = '1'
            os.environ['MEDIAPIPE_ENABLE_GPU'] = '1'
            
            if gpu_available:
                try:
                    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
                except:
                    pass
        
        try:
            self._pose = self._mp_pose.Pose(
                static_image_mode=False,
                model_complexity=0,
                min_detection_confidence=POSE_MIN_DETECTION_CONFIDENCE,
                min_tracking_confidence=POSE_MIN_TRACKING_CONFIDENCE
            )
        except Exception as e:
            print(f"Failed to initialize MediaPipe Pose with GPU: {e}")
            print("Falling back to CPU mode...")
            os.environ.pop('MEDIAPIPE_GPU', None)
            os.environ.pop('MEDIAPIPE_ENABLE_GPU', None)
            
            self._pose = self._mp_pose.Pose(
                static_image_mode=False,
                model_complexity=0,
                min_detection_confidence=POSE_MIN_DETECTION_CONFIDENCE,
                min_tracking_confidence=POSE_MIN_TRACKING_CONFIDENCE
            )
            self._gpu_available = False
        
        self._is_initialized = True
        
        self._is_detecting = True
        self._detection_thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._detection_thread.start()
        
        if self._gpu_available:
            print("MediaPipe Pose initialized with GPU acceleration")
        else:
            print("MediaPipe Pose initialized with CPU")
    
    def _detection_loop(self):
        while self._is_detecting and self._pose is not None:
            frame = None
            frame_id = 0
            
            with self._frame_lock:
                if self._latest_frame is not None:
                    frame = self._latest_frame.copy()
                    frame_id = self._last_frame_id
            
            if frame is not None:
                if frame_id <= self._processed_frame_id:
                    time.sleep(0.001)
                    continue
                
                left_hand = RawHandData()
                right_hand = RawHandData()
                timestamp = time.time()
                
                try:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = self._pose.process(rgb_frame)
                    
                    if results.pose_landmarks:
                        left_wrist_lm = results.pose_landmarks.landmark[self.POSE_LANDMARKS['left_wrist']]
                        right_wrist_lm = results.pose_landmarks.landmark[self.POSE_LANDMARKS['right_wrist']]
                        
                        if left_wrist_lm.visibility > 0.5:
                            screen_point = self._landmark_to_screen(left_wrist_lm)
                            left_hand.is_detected = True
                            left_hand.x = screen_point[0]
                            left_hand.y = screen_point[1]
                            left_hand.confidence = left_wrist_lm.visibility
                            left_hand.hand_type = 'left'
                        
                        if right_wrist_lm.visibility > 0.5:
                            screen_point = self._landmark_to_screen(right_wrist_lm)
                            right_hand.is_detected = True
                            right_hand.x = screen_point[0]
                            right_hand.y = screen_point[1]
                            right_hand.confidence = right_wrist_lm.visibility
                            right_hand.hand_type = 'right'
                except Exception:
                    pass
                
                left_hand.timestamp = timestamp
                right_hand.timestamp = timestamp
                
                with self._result_lock:
                    self._left_hand = left_hand
                    self._right_hand = right_hand
                    self._processed_frame_id = frame_id
                
                if self.on_hand_updated:
                    self.on_hand_updated(self._left_hand, self._right_hand)
            else:
                time.sleep(0.005)
    
    def submit_frame(self, frame):
        if not self._is_initialized or self._pose is None:
            return
        
        with self._frame_lock:
            self._latest_frame = frame.copy()
            self._last_frame_id += 1
    
    def get_latest_result(self):
        with self._result_lock:
            left = RawHandData()
            left.is_detected = self._left_hand.is_detected
            left.x = self._left_hand.x
            left.y = self._left_hand.y
            left.confidence = self._left_hand.confidence
            left.hand_type = self._left_hand.hand_type
            left.timestamp = self._left_hand.timestamp
            
            right = RawHandData()
            right.is_detected = self._right_hand.is_detected
            right.x = self._right_hand.x
            right.y = self._right_hand.y
            right.confidence = self._right_hand.confidence
            right.hand_type = self._right_hand.hand_type
            right.timestamp = self._right_hand.timestamp
        
        return left, right
    
    def _landmark_to_screen(self, landmark):
        # 摄像头裁剪后分辨率 1280×720，比例 16:9
        camera_ratio = 1280.0 / 720.0
        screen_ratio = SCREEN_WIDTH / SCREEN_HEIGHT
        
        if screen_ratio > camera_ratio:
            effective_width = SCREEN_HEIGHT * camera_ratio
            effective_height = SCREEN_HEIGHT
            offset_x = (SCREEN_WIDTH - effective_width) / 2
            offset_y = 0
        else:
            effective_width = SCREEN_WIDTH
            effective_height = SCREEN_WIDTH / camera_ratio
            offset_x = 0
            offset_y = (SCREEN_HEIGHT - effective_height) / 2
        
        x = landmark.x * effective_width + offset_x
        y = landmark.y * effective_height + offset_y
        
        x = max(0, min(SCREEN_WIDTH, x))
        y = max(0, min(SCREEN_HEIGHT, y))
        
        return (x, y)
    
    def get_left_hand(self):
        return self._left_hand
    
    def get_right_hand(self):
        return self._right_hand
    
    def process_frame(self, frame):
        self.submit_frame(frame)
        return self.get_latest_result()
    
    def release(self):
        self._is_detecting = False
        
        if self._detection_thread is not None:
            self._detection_thread.join(timeout=1.0)
            self._detection_thread = None
        
        if self._pose is not None:
            self._pose.close()
            self._pose = None
        
        self._is_initialized = False