import math


class OneEuroFilter:
    DEFAULT_MIN_CUTOFF = 1.0
    DEFAULT_BETA = 0.007
    DEFAULT_D_CUTOFF = 1.0
    
    def __init__(self, min_cutoff=DEFAULT_MIN_CUTOFF, beta=DEFAULT_BETA, d_cutoff=DEFAULT_D_CUTOFF):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        
        self._x_prev = None
        self._dx_prev = 0.0
        self._last_time = None
        self._initialized = False
    
    def _alpha(self, cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)
    
    def filter(self, x, timestamp=None):
        if timestamp is None:
            import time
            timestamp = time.time()
        
        if not self._initialized:
            self._x_prev = x
            self._last_time = timestamp
            self._initialized = True
            return x
        
        dt = timestamp - self._last_time
        if dt <= 0:
            return self._x_prev
        
        if dt > 0.1:
            dt = 0.1
        
        dx = (x - self._x_prev) / dt
        
        alpha_d = self._alpha(self.d_cutoff, dt)
        dx_smoothed = self._dx_prev + alpha_d * (dx - self._dx_prev)
        
        cutoff = self.min_cutoff + self.beta * abs(dx_smoothed)
        
        alpha = self._alpha(cutoff, dt)
        x_filtered = self._x_prev + alpha * (x - self._x_prev)
        
        self._x_prev = x_filtered
        self._dx_prev = dx_smoothed
        self._last_time = timestamp
        
        return x_filtered
    
    def reset(self):
        self._x_prev = None
        self._dx_prev = 0.0
        self._last_time = None
        self._initialized = False
    
    @property
    def is_initialized(self):
        return self._initialized


class TwoDimensionalOneEuroFilter:
    def __init__(self, min_cutoff=OneEuroFilter.DEFAULT_MIN_CUTOFF, 
                 beta=OneEuroFilter.DEFAULT_BETA, d_cutoff=OneEuroFilter.DEFAULT_D_CUTOFF):
        self._x_filter = OneEuroFilter(min_cutoff, beta, d_cutoff)
        self._y_filter = OneEuroFilter(min_cutoff, beta, d_cutoff)
        self._min_cutoff = min_cutoff
        self._beta = beta
        self._d_cutoff = d_cutoff
    
    def filter(self, x, y, timestamp=None):
        filtered_x = self._x_filter.filter(x, timestamp)
        filtered_y = self._y_filter.filter(y, timestamp)
        return filtered_x, filtered_y
    
    def reset(self):
        self._x_filter.reset()
        self._y_filter.reset()
    
    @property
    def is_initialized(self):
        return self._x_filter.is_initialized and self._y_filter.is_initialized