import cv2
import numpy as np
import threading
import time

from config import CAMERA_DEVICE, CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS, CAMERA_SIDE


class CameraManager:
    def __init__(self):
        self._cap = None
        self._is_running = False
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._capture_thread = None
    
    def initialize(self, device=CAMERA_DEVICE):
        try:
            self._cap = cv2.VideoCapture(device)
            
            if not self._cap.isOpened():
                print(f"Failed to open camera: {device}")
                return False
            
            # 注意：此双目摄像头驱动固定输出 2560×720，OpenCV set() 不生效
            # 保留以下设置以兼容其他摄像头，但对此设备无实际效果
            # self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            # self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
            self._cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
            
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            self._cap.set(cv2.CAP_PROP_FOURCC, fourcc)
            
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            actual_width = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            actual_height = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            print(f"Camera raw output: {actual_width}x{actual_height}")
            print(f"Camera side: {CAMERA_SIDE}, crop to: {CAMERA_WIDTH}x{CAMERA_HEIGHT}")
            
            self._is_running = True
            
            self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            
            time.sleep(0.5)
            
            return True
        except Exception as e:
            print(f"Camera initialization error: {e}")
            if self._cap is not None:
                self._cap.release()
            return False
    
    def _capture_loop(self):
        while self._is_running and self._cap is not None:
            ret, frame = self._cap.read()
            
            if ret:
                # 双目摄像头：原始 2560×720，左右各 1280×720 拼接
                # 裁剪为单目 1280×720，再做镜像翻转
                if CAMERA_SIDE == "left":
                    single_frame = frame[:, 0:1280]
                else:
                    single_frame = frame[:, 1280:2560]
                
                single_frame = cv2.flip(single_frame, 1)
                
                with self._frame_lock:
                    self._latest_frame = single_frame.copy()
            else:
                time.sleep(0.01)
    
    def get_frame(self):
        if not self._is_running:
            return None
        
        with self._frame_lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy()
        
        return None
    
    def get_stereo_frames(self):
        """已废弃：CameraManager 现在直接返回单目图像，此函数保留仅作兼容"""
        frame = self.get_frame()
        if frame is None:
            return None, None
        return frame, None
    
    def release(self):
        self._is_running = False
        
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=1.0)
            self._capture_thread = None
        
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        
        self._latest_frame = None
    
    @property
    def is_running(self):
        return self._is_running


def test_camera():
    camera = CameraManager()
    
    if not camera.initialize():
        print("Camera initialization failed")
        return
    
    print("Camera initialized successfully")
    
    for i in range(10):
        frame = camera.get_frame()
        
        if frame is not None:
            print(f"Frame {i}: shape={frame.shape}")
            
            left, right = camera.get_stereo_frames()
            
            if left is not None:
                print(f"  Left frame: shape={left.shape}")
            if right is not None:
                print(f"  Right frame: shape={right.shape}")
        else:
            print(f"Frame {i}: None")
    
    camera.release()
    print("Camera released")


if __name__ == "__main__":
    test_camera()