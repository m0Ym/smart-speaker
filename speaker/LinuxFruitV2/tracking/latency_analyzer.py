import time
import numpy as np


class LatencyAnalyzer:
    def __init__(self, window_size=60):
        self._window_size = window_size
        self._timestamps = {
            'capture': [],
            'inference': [],
            'filter': [],
            'predict': [],
            'render': []
        }
        self._latencies = []
    
    def record_capture(self):
        self._timestamps['capture'].append(time.time())
        self._trim()
    
    def record_inference(self):
        self._timestamps['inference'].append(time.time())
        self._trim()
    
    def record_filter(self):
        self._timestamps['filter'].append(time.time())
        self._trim()
    
    def record_predict(self):
        self._timestamps['predict'].append(time.time())
        self._trim()
    
    def record_render(self):
        self._timestamps['render'].append(time.time())
        self._trim()
        
        self._compute_latency()
    
    def _trim(self):
        for key in self._timestamps:
            if len(self._timestamps[key]) > self._window_size:
                self._timestamps[key].pop(0)
        
        if len(self._latencies) > self._window_size:
            self._latencies.pop(0)
    
    def _compute_latency(self):
        keys = ['capture', 'inference', 'filter', 'predict', 'render']
        min_len = min(len(self._timestamps[k]) for k in keys)
        
        if min_len >= 2:
            latest_idx = -1
            
            capture_t = self._timestamps['capture'][latest_idx]
            render_t = self._timestamps['render'][latest_idx]
            
            end_to_end = (render_t - capture_t) * 1000
            self._latencies.append(end_to_end)
    
    def get_latency_summary(self):
        if len(self._latencies) == 0:
            return {
                'avg_latency_ms': 0,
                'min_latency_ms': 0,
                'max_latency_ms': 0,
                'std_latency_ms': 0,
                'jitter_ms': 0,
                'fps': 0
            }
        
        latencies = np.array(self._latencies)
        
        avg_latency = np.mean(latencies)
        min_latency = np.min(latencies)
        max_latency = np.max(latencies)
        std_latency = np.std(latencies)
        
        jitter = std_latency
        
        if avg_latency > 0:
            fps = 1000 / avg_latency
        else:
            fps = 0
        
        return {
            'avg_latency_ms': avg_latency,
            'min_latency_ms': min_latency,
            'max_latency_ms': max_latency,
            'std_latency_ms': std_latency,
            'jitter_ms': jitter,
            'fps': fps
        }
    
    def get_stage_times(self):
        keys = ['capture', 'inference', 'filter', 'predict', 'render']
        min_len = min(len(self._timestamps[k]) for k in keys)
        
        if min_len < 2:
            return {}
        
        stage_times = {}
        
        for i in range(1, len(keys)):
            prev_key = keys[i-1]
            curr_key = keys[i]
            
            times = []
            for j in range(len(self._timestamps[prev_key])):
                if j < len(self._timestamps[curr_key]):
                    dt = (self._timestamps[curr_key][j] - self._timestamps[prev_key][j]) * 1000
                    times.append(dt)
            
            if times:
                stage_times[f'{prev_key}_to_{curr_key}'] = {
                    'avg': np.mean(times),
                    'min': np.min(times),
                    'max': np.max(times),
                    'std': np.std(times)
                }
        
        return stage_times
    
    def reset(self):
        for key in self._timestamps:
            self._timestamps[key] = []
        self._latencies = []