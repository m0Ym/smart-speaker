import math
import time


class VelocityEstimator:
    DEFAULT_HISTORY_SIZE = 5
    
    def __init__(self, history_size=DEFAULT_HISTORY_SIZE):
        self._history_size = history_size
        self._positions = []
        self._timestamps = []
        self._weights = self._compute_weights(history_size)
        
        self._current_vx = 0.0
        self._current_vy = 0.0
        self._current_speed = 0.0
        self._current_accel = 0.0
        self._initialized = False
    
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
            self._initialized = True
            if len(self._positions) >= 3:
                self._compute_acceleration()
    
    def _compute_velocity(self):
        vx_sum = 0.0
        vy_sum = 0.0
        weight_sum = 0.0
        
        num_segments = len(self._positions) - 1
        for i in range(1, len(self._positions)):
            dt = self._timestamps[i] - self._timestamps[i-1]
            if dt <= 0 or dt > 0.1:
                continue
            
            dx = self._positions[i][0] - self._positions[i-1][0]
            dy = self._positions[i][1] - self._positions[i-1][1]
            
            weight_idx = num_segments - i
            weight = self._weights[min(weight_idx, len(self._weights) - 1)]
            
            vx_sum += (dx / dt) * weight
            vy_sum += (dy / dt) * weight
            weight_sum += weight
        
        if weight_sum > 0:
            self._current_vx = vx_sum / weight_sum
            self._current_vy = vy_sum / weight_sum
        else:
            self._current_vx = 0.0
            self._current_vy = 0.0
        
        self._current_speed = math.sqrt(self._current_vx ** 2 + self._current_vy ** 2)
    
    def _compute_acceleration(self):
        if len(self._positions) < 3:
            return
        
        dt1 = self._timestamps[-1] - self._timestamps[-2]
        dt2 = self._timestamps[-2] - self._timestamps[-3]
        
        if dt1 <= 0 or dt2 <= 0 or dt1 > 0.1 or dt2 > 0.1:
            return
        
        dx1 = self._positions[-1][0] - self._positions[-2][0]
        dy1 = self._positions[-1][1] - self._positions[-2][1]
        
        dx2 = self._positions[-2][0] - self._positions[-3][0]
        dy2 = self._positions[-2][1] - self._positions[-3][1]
        
        vx1 = dx1 / dt1
        vy1 = dy1 / dt1
        
        vx2 = dx2 / dt2
        vy2 = dy2 / dt2
        
        dvx = vx1 - vx2
        dvy = vy1 - vy2
        
        dt_avg = (dt1 + dt2) / 2
        
        self._current_accel = math.sqrt(dvx**2 + dvy**2) / dt_avg
    
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
    def acceleration(self):
        return self._current_accel
    
    @property
    def velocity(self):
        return (self._current_vx, self._current_vy)
    
    @property
    def is_initialized(self):
        return self._initialized
    
    def reset(self):
        self._positions = []
        self._timestamps = []
        self._current_vx = 0.0
        self._current_vy = 0.0
        self._current_speed = 0.0
        self._current_accel = 0.0
        self._initialized = False