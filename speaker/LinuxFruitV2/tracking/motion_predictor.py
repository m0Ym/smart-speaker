import math


class MotionPredictor:
    def __init__(self, prediction_time=0.033):
        self._prediction_time = prediction_time
        self._last_x = 0.0
        self._last_y = 0.0
        self._last_vx = 0.0
        self._last_vy = 0.0
    
    def predict(self, x, y, vx, vy):
        self._last_x = x
        self._last_y = y
        self._last_vx = vx
        self._last_vy = vy
        
        predicted_x = x + vx * self._prediction_time
        predicted_y = y + vy * self._prediction_time
        
        return predicted_x, predicted_y
    
    def get_prediction(self):
        return (
            self._last_x + self._last_vx * self._prediction_time,
            self._last_y + self._last_vy * self._prediction_time
        )
    
    @property
    def prediction_time(self):
        return self._prediction_time
    
    @prediction_time.setter
    def prediction_time(self, value):
        self._prediction_time = value
    
    def reset(self):
        self._last_x = 0.0
        self._last_y = 0.0
        self._last_vx = 0.0
        self._last_vy = 0.0