import math


class OneEuroFilter:
    def __init__(self, min_cutoff=1.0, beta=0.007, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        
        self._x_prev = None
        self._dx_prev = 0.0
        self._last_time = None
    
    def _alpha(self, cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)
    
    def filter(self, x, timestamp=None):
        if timestamp is None:
            import time
            timestamp = time.time()
        
        if self._last_time is None:
            self._x_prev = x
            self._last_time = timestamp
            return x
        
        dt = timestamp - self._last_time
        if dt <= 0:
            return self._x_prev
        
        dx = (x - self._x_prev) / dt
        dx_smoothed = self._x_prev + self._alpha(self.d_cutoff, dt) * (dx - self._dx_prev)
        
        cutoff = self.min_cutoff + self.beta * abs(dx_smoothed)
        
        x_filtered = self._x_prev + self._alpha(cutoff, dt) * (x - self._x_prev)
        
        self._x_prev = x_filtered
        self._dx_prev = dx_smoothed
        self._last_time = timestamp
        
        return x_filtered


class TwoDimensionalOneEuroFilter:
    def __init__(self, min_cutoff=1.0, beta=0.007, d_cutoff=1.0):
        self._x_filter = OneEuroFilter(min_cutoff, beta, d_cutoff)
        self._y_filter = OneEuroFilter(min_cutoff, beta, d_cutoff)
    
    def filter(self, x, y, timestamp=None):
        filtered_x = self._x_filter.filter(x, timestamp)
        filtered_y = self._y_filter.filter(y, timestamp)
        return filtered_x, filtered_y
    
    def reset(self):
        self._x_filter = OneEuroFilter(
            self._x_filter.min_cutoff,
            self._x_filter.beta,
            self._x_filter.d_cutoff
        )
        self._y_filter = OneEuroFilter(
            self._y_filter.min_cutoff,
            self._y_filter.beta,
            self._y_filter.d_cutoff
        )