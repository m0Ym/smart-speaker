import math
import time


class SlashEvent:
    def __init__(self, start_pos, end_pos, trajectory, speed, direction, score):
        self.start_pos = start_pos
        self.end_pos = end_pos
        self.trajectory = trajectory
        self.speed = speed
        self.direction = direction
        self.score = score
        self.timestamp = time.time()
    
    @property
    def length(self):
        dx = self.end_pos[0] - self.start_pos[0]
        dy = self.end_pos[1] - self.start_pos[1]
        return math.sqrt(dx**2 + dy**2)
    
    def get_direction_vector(self):
        dx = self.end_pos[0] - self.start_pos[0]
        dy = self.end_pos[1] - self.start_pos[1]
        length = self.length
        if length > 0:
            return (dx / length, dy / length)
        return (0, 0)
    
    def get_full_trajectory(self):
        return list(self.trajectory)


class SlashDetector:
    DEFAULT_SPEED_THRESHOLD = 100.0
    DEFAULT_MIN_DISTANCE = 30.0
    DEFAULT_MIN_DURATION = 0.05
    DEFAULT_DIRECTION_THRESHOLD = 0.75
    DEFAULT_HISTORY_SIZE = 40
    DEFAULT_SCORE_THRESHOLD = 0.6
    
    def __init__(self, speed_threshold=DEFAULT_SPEED_THRESHOLD, 
                 min_distance=DEFAULT_MIN_DISTANCE, 
                 min_duration=DEFAULT_MIN_DURATION, 
                 direction_threshold=DEFAULT_DIRECTION_THRESHOLD,
                 history_size=DEFAULT_HISTORY_SIZE, 
                 score_threshold=DEFAULT_SCORE_THRESHOLD):
        self._speed_threshold = speed_threshold
        self._min_distance = min_distance
        self._min_duration = min_duration
        self._direction_threshold = direction_threshold
        self._score_threshold = score_threshold
        
        self._trajectory = []
        self._timestamps = []
        self._speeds = []
        self._history_size = history_size
        
        self._current_slash = None
        self._slash_start_time = None
        self._slash_start_index = 0
    
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
        avg_dir_y = sum(d[1] for d in directions) / len(directions)
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
        return min(1.0, distance / (self._min_distance * 4))
    
    def _compute_direction_score(self, consistency):
        if consistency < self._direction_threshold:
            return 0.0
        return consistency
    
    def update(self, x, y, speed, timestamp=None):
        if timestamp is None:
            timestamp = time.time()

        self._trajectory.append((x, y))
        self._timestamps.append(timestamp)
        self._speeds.append(speed)

        if len(self._trajectory) > self._history_size:
            self._trajectory.pop(0)
            self._timestamps.pop(0)
            self._speeds.pop(0)
            if self._slash_start_index > 0:
                self._slash_start_index -= 1

        if speed > self._speed_threshold:
            if self._slash_start_time is None:
                self._slash_start_time = timestamp
                self._slash_start_index = max(0, len(self._trajectory) - 1)
            else:
                duration = timestamp - self._slash_start_time
                if duration >= self._min_duration:
                    event = self._evaluate_slash()
                    if event:
                        self._current_slash = event
                        self._slash_start_time = timestamp
                        self._slash_start_index = max(0, len(self._trajectory) - 1)
                        return event
        else:
            if self._slash_start_time is not None:
                duration = timestamp - self._slash_start_time
                if duration >= self._min_duration:
                    event = self._evaluate_slash()
                    if event:
                        self._current_slash = event
                        self._reset_trajectory()
                        return event

            self._slash_start_time = None

        return None
    
    def _evaluate_slash(self):
        if len(self._trajectory) < 3:
            return None
        
        if self._slash_start_index >= len(self._trajectory):
            return None
        
        valid_trajectory = self._trajectory[self._slash_start_index:]
        valid_timestamps = self._timestamps[self._slash_start_index:]
        
        if len(valid_trajectory) < 3:
            return None
        
        duration = valid_timestamps[-1] - valid_timestamps[0]
        
        if duration < self._min_duration:
            return None
        
        distance = 0.0
        for i in range(1, len(valid_trajectory)):
            dx = valid_trajectory[i][0] - valid_trajectory[i-1][0]
            dy = valid_trajectory[i][1] - valid_trajectory[i-1][1]
            distance += math.sqrt(dx ** 2 + dy ** 2)
        
        if distance < self._min_distance:
            return None
        
        avg_speed = distance / duration
        
        directions = []
        for i in range(1, len(valid_trajectory)):
            dx = valid_trajectory[i][0] - valid_trajectory[i-1][0]
            dy = valid_trajectory[i][1] - valid_trajectory[i-1][1]
            dist = math.sqrt(dx ** 2 + dy ** 2)
            if dist > 0:
                directions.append((dx / dist, dy / dist))
        
        if len(directions) >= 2:
            avg_dir_x = sum(d[0] for d in directions) / len(directions)
            avg_dir_y = sum(d[1] for d in directions) / len(directions)
            avg_dist = math.sqrt(avg_dir_x ** 2 + avg_dir_y ** 2)
            if avg_dist > 0:
                avg_dir_x /= avg_dist
                avg_dir_y /= avg_dist
            
            dot_products = []
            for d in directions:
                dot = d[0] * avg_dir_x + d[1] * avg_dir_y
                dot_products.append(max(0, dot))
            
            direction_consistency = sum(dot_products) / len(dot_products)
        else:
            direction_consistency = 1.0
        
        speed_score = self._compute_speed_score(avg_speed)
        distance_score = self._compute_distance_score(distance)
        direction_score = self._compute_direction_score(direction_consistency)

        total_score = (
            0.35 * speed_score +
            0.35 * distance_score +
            0.30 * direction_score
        )
        
        if total_score >= self._score_threshold:
            dx = valid_trajectory[-1][0] - valid_trajectory[0][0]
            dy = valid_trajectory[-1][1] - valid_trajectory[0][1]
            length = math.sqrt(dx**2 + dy**2)
            
            if length > 0:
                direction_vec = (dx / length, dy / length)
            else:
                direction_vec = (0, 0)
            
            return SlashEvent(
                start_pos=valid_trajectory[0],
                end_pos=valid_trajectory[-1],
                trajectory=list(valid_trajectory),
                speed=avg_speed,
                direction=direction_vec,
                score=total_score
            )
        
        return None
    
    @property
    def current_slash(self):
        return self._current_slash
    
    @property
    def trajectory(self):
        return list(self._trajectory)
    
    def _reset_trajectory(self):
        keep_count = min(5, len(self._trajectory))
        if keep_count >= 2:
            self._trajectory = self._trajectory[-keep_count:]
            self._timestamps = self._timestamps[-keep_count:]
            self._speeds = self._speeds[-keep_count:]
            self._slash_start_index = 0
        else:
            self._trajectory = []
            self._timestamps = []
            self._speeds = []
            self._slash_start_index = 0
    
    @property
    def is_slashing(self):
        return self._slash_start_time is not None
    
    def reset(self):
        self._trajectory = []
        self._timestamps = []
        self._speeds = []
        self._current_slash = None
        self._slash_start_time = None
        self._slash_start_index = 0