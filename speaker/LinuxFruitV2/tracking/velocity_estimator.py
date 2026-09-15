import math
import time


class VelocityEstimator:
    def __init__(self, history_size=5):
        self._history_size = history_size
        self._positions = []
        self._timestamps = []
        self._weights = self._compute_weights(history_size)
        
        self._current_vx = 0.0
        self._current_vy = 0.0
        self._current_speed = 0.0
    
    def _compute_weights(self, size):
        if size <= 1:
            return [1.0]
        
        total = 0.0
        weights = []
        for i in range(size):
            w = (i + 1) ** 2
            weights.append(w)
            total += w
        
        return [w / total for w in weights]
    
    def update(self, x, y, timestamp=None):
        if timestamp is None:
            timestamp = time.time()
        
        self._positions.append((x, y))
        self._timestamps.append(timestamp)
        
        if len(self._positions) > self._history_size:
            self._positions.pop(0)
            self._timestamps.pop(0)
        
        if len(self._positions) >= 2:
            self._compute_velocity()
    
    def _compute_velocity(self):
        vx_sum = 0.0
        vy_sum = 0.0
        
        for i in range(1, len(self._positions)):
            dt = self._timestamps[i] - self._timestamps[i-1]
            if dt <= 0:
                continue
            
            dx = self._positions[i][0] - self._positions[i-1][0]
            dy = self._positions[i][1] - self._positions[i-1][1]
            
            weight = self._weights[min(i, len(self._weights) - 1)]
            
            vx_sum += (dx / dt) * weight
            vy_sum += (dy / dt) * weight
        
        self._current_vx = vx_sum
        self._current_vy = vy_sum
        self._current_speed = math.sqrt(vx_sum ** 2 + vy_sum ** 2)
    
    @property
    def vx(self):
        return self._current_vx
    
    @property
    def vy(self):
        return self._current_vy
    
    @property
    def speed(self):
        return self._current_speed
    
    @property
    def velocity(self):
        return (self._current_vx, self._current_vy)
    
    def reset(self):
        self._positions = []
        self._timestamps = []
        self._current_vx = 0.0
        self._current_vy = 0.0
        self._current_speed = 0.0