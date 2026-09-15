import math


class MotionPredictor:
    DEFAULT_PREDICTION_TIME = 0.033
    
    def __init__(self, prediction_time=DEFAULT_PREDICTION_TIME):
        self._prediction_time = prediction_time
        self._last_x = 0.0
        self._last_y = 0.0
        self._last_vx = 0.0
        self._last_vy = 0.0
        self._last_accel = 0.0
        self._initialized = False
    
    def predict(self, x, y, vx, vy, accel=0.0):
        self._last_x = x
        self._last_y = y
        self._last_vx = vx
        self._last_vy = vy
        self._last_accel = accel
        self._initialized = True
        
        predicted_x = x + vx * self._prediction_time
        predicted_y = y + vy * self._prediction_time
        
        return predicted_x, predicted_y
    
    def get_prediction(self):
        if not self._initialized:
            return (self._last_x, self._last_y)
        
        return (
            self._last_x + self._last_vx * self._prediction_time,
            self._last_y + self._last_vy * self._prediction_time
        )
    
    def predict_with_latency(self, x, y, vx, vy, latency=0.0):
        effective_latency = max(0, latency)
        
        predicted_x = x + vx * effective_latency
        predicted_y = y + vy * effective_latency
        
        return predicted_x, predicted_y
    
    @property
    def prediction_time(self):
        return self._prediction_time
    
    @prediction_time.setter
    def prediction_time(self, value):
        self._prediction_time = max(0.0, min(0.1, value))
    
    @property
    def is_initialized(self):
        return self._initialized
    
    def reset(self):
        self._last_x = 0.0
        self._last_y = 0.0
        self._last_vx = 0.0
        self._last_vy = 0.0
        self._last_accel = 0.0
        self._initialized = False