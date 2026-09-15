import math
import time


class SliceDetector:
    def __init__(self, speed_threshold=100.0, min_distance=30.0, 
                 min_duration=0.05, direction_threshold=0.8,
                 history_size=10, score_threshold=0.7):
        self._speed_threshold = speed_threshold
        self._min_distance = min_distance
        self._min_duration = min_duration
        self._direction_threshold = direction_threshold
        self._score_threshold = score_threshold
        
        self._trajectory = []
        self._timestamps = []
        self._history_size = history_size
        
        self._current_slice = None
        self._slice_start_time = None
        
    def _compute_direction_consistency(self):
        if len(self._trajectory) < 3:
            return 1.0
        
        directions = []
        for i in range(1, len(self._trajectory)):
            dx = self._trajectory[i][0] - self._trajectory[i-1][0]
            dy = self._trajectory[i][1] - self._trajectory[i-1][1]
            dist = math.sqrt(dx ** 2 + dy ** 2)
            if dist > 0:
                directions.append((dx / dist, dy / dist))
        
        if len(directions) < 2:
            return 1.0
        
        avg_dir_x = sum(d[0] for d in directions) / len(directions)
        avg_dir_y = sum(d[1] for d in directions)
        avg_dist = math.sqrt(avg_dir_x ** 2 + avg_dir_y ** 2)
        if avg_dist > 0:
            avg_dir_x /= avg_dist
            avg_dir_y /= avg_dist
        
        dot_products = []
        for d in directions:
            dot = d[0] * avg_dir_x + d[1] * avg_dir_y
            dot_products.append(max(0, dot))
        
        return sum(dot_products) / len(dot_products)
    
    def _compute_trajectory_distance(self):
        if len(self._trajectory) < 2:
            return 0.0
        
        total_dist = 0.0
        for i in range(1, len(self._trajectory)):
            dx = self._trajectory[i][0] - self._trajectory[i-1][0]
            dy = self._trajectory[i][1] - self._trajectory[i-1][1]
            total_dist += math.sqrt(dx ** 2 + dy ** 2)
        
        return total_dist
    
    def _compute_speed_score(self, speed):
        if speed < self._speed_threshold:
            return 0.0
        return min(1.0, speed / (self._speed_threshold * 3))
    
    def _compute_distance_score(self, distance):
        if distance < self._min_distance:
            return 0.0
        return min(1.0, distance / (self._min_distance * 3))
    
    def _compute_direction_score(self, consistency):
        if consistency < self._direction_threshold:
            return 0.0
        return consistency
    
    def update(self, x, y, speed, timestamp=None):
        if timestamp is None:
            timestamp = time.time()
        
        self._trajectory.append((x, y))
        self._timestamps.append(timestamp)
        
        if len(self._trajectory) > self._history_size:
            self._trajectory.pop(0)
            self._timestamps.pop(0)
        
        if speed > self._speed_threshold:
            if self._slice_start_time is None:
                self._slice_start_time = timestamp
        else:
            self._slice_start_time = None
        
        return self._evaluate_slice()
    
    def _evaluate_slice(self):
        if len(self._trajectory) < 3:
            return False
        
        duration = self._timestamps[-1] - self._timestamps[0]
        
        if duration < self._min_duration:
            return False
        
        distance = self._compute_trajectory_distance()
        direction_consistency = self._compute_direction_consistency()
        
        if distance < self._min_distance:
            self._reset_trajectory()
            return False
        
        avg_speed = distance / duration
        
        speed_score = self._compute_speed_score(avg_speed)
        distance_score = self._compute_distance_score(distance)
        direction_score = self._compute_direction_score(direction_consistency)
        
        total_score = (
            0.4 * speed_score +
            0.3 * distance_score +
            0.3 * direction_score
        )
        
        if total_score >= self._score_threshold:
            self._current_slice = {
                'start': self._trajectory[0],
                'end': self._trajectory[-1],
                'points': list(self._trajectory),
                'score': total_score,
                'speed': avg_speed,
                'distance': distance,
                'direction': direction_consistency
            }
            
            self._reset_trajectory()
            return True
        
        return False
    
    def _reset_trajectory(self):
        if len(self._trajectory) >= 2:
            self._trajectory = [self._trajectory[-1]]
            self._timestamps = [self._timestamps[-1]]
        else:
            self._trajectory = []
            self._timestamps = []
    
    @property
    def current_slice(self):
        return self._current_slice
    
    @property
    def trajectory(self):
        return list(self._trajectory)
    
    def reset(self):
        self._trajectory = []
        self._timestamps = []
        self._current_slice = None
        self._slice_start_time = None