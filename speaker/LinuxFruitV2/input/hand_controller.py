import math
import time

from filter.one_euro_filter import TwoDimensionalOneEuroFilter
from filter.velocity_estimator import VelocityEstimator
from filter.motion_predictor import MotionPredictor
from gesture.slash_detector import SlashDetector


class HandState:
    def __init__(self):
        self.raw_position = (0.0, 0.0)
        self.filtered_position = (0.0, 0.0)
        self.predicted_position = (0.0, 0.0)
        self.prev_raw_position = (0.0, 0.0)
        self.prev_filtered_position = (0.0, 0.0)
        self.velocity = (0.0, 0.0)
        self.speed = 0.0
        self.acceleration = 0.0
        self.trail = []
        self.is_tracking = False
        self._last_update_time = 0.0
        self._last_update_timestamp = 0.0
    
    def update_trail(self, position):
        self.trail.append(position)
        if len(self.trail) > 20:
            self.trail.pop(0)
    
    def clear_trail(self):
        self.trail = []


class HandController:
    LOST_THRESHOLD = 8
    
    def __init__(self):
        self._left_hand = HandState()
        self._right_hand = HandState()
        
        self._left_filter = TwoDimensionalOneEuroFilter()
        self._right_filter = TwoDimensionalOneEuroFilter()
        
        self._left_velocity = VelocityEstimator()
        self._right_velocity = VelocityEstimator()
        
        self._left_predictor = MotionPredictor()
        self._right_predictor = MotionPredictor()
        
        self._left_slash_detector = SlashDetector()
        self._right_slash_detector = SlashDetector()
        
        self._left_lost_count = 0
        self._right_lost_count = 0
        
        self._frame_count = 0
        
        self.on_slash = None
        self.on_hand_moved = None
    
    def _get_hand_components(self, hand_id):
        if hand_id == 'left':
            return (
                self._left_hand,
                self._left_filter,
                self._left_velocity,
                self._left_predictor,
                self._left_slash_detector,
                'left'
            )
        else:
            return (
                self._right_hand,
                self._right_filter,
                self._right_velocity,
                self._right_predictor,
                self._right_slash_detector,
                'right'
            )
    
    def update_hand(self, hand_id, raw_x, raw_y, timestamp=None):
        if timestamp is None:
            timestamp = time.time()

        hand, filter_, velocity, predictor, slash_detector, _ = self._get_hand_components(hand_id)

        hand.prev_raw_position = hand.raw_position
        hand.prev_filtered_position = hand.filtered_position
        prev_timestamp = hand._last_update_timestamp

        hand.raw_position = (raw_x, raw_y)
        hand._last_update_time = timestamp
        hand._last_update_timestamp = timestamp

        hand.filtered_position = filter_.filter(raw_x, raw_y, timestamp)

        velocity.update(hand.filtered_position[0], hand.filtered_position[1], timestamp)
        hand.velocity = velocity.velocity
        hand.speed = velocity.speed
        hand.acceleration = velocity.acceleration

        vx, vy = velocity.velocity if velocity.is_initialized else (0, 0)
        hand.predicted_position = predictor.predict(
            hand.filtered_position[0],
            hand.filtered_position[1],
            vx, vy,
            velocity.acceleration
        )

        hand.is_tracking = True
        hand.update_trail(hand.predicted_position)
        
        if hand_id == 'left':
            self._left_lost_count = 0
        else:
            self._right_lost_count = 0
        
        slash_event = slash_detector.update(
            hand.predicted_position[0],
            hand.predicted_position[1],
            hand.speed,
            timestamp
        )
        
        if slash_event and self.on_slash:
            self.on_slash(slash_event, hand_id)
        
        if self.on_hand_moved:
            self.on_hand_moved(hand_id, hand.predicted_position, hand.speed)
        
        self._frame_count += 1
    
    def update_with_dt(self, hand_id, raw_x, raw_y, delta_time):
        timestamp = time.time()
        self.update_hand(hand_id, raw_x, raw_y, timestamp)
    
    def track_lost(self, hand_id):
        if hand_id == 'left':
            if self._left_lost_count < self.LOST_THRESHOLD:
                self._left_lost_count += 1
                if self._left_lost_count == self.LOST_THRESHOLD:
                    self._left_hand.is_tracking = False
                    self._left_hand.trail = []
                    self._left_filter.reset()
                    self._left_velocity.reset()
                    self._left_predictor.reset()
                    self._left_slash_detector.reset()
        else:
            if self._right_lost_count < self.LOST_THRESHOLD:
                self._right_lost_count += 1
                if self._right_lost_count == self.LOST_THRESHOLD:
                    self._right_hand.is_tracking = False
                    self._right_hand.trail = []
                    self._right_filter.reset()
                    self._right_velocity.reset()
                    self._right_predictor.reset()
                    self._right_slash_detector.reset()
    
    def get_hand_state(self, hand_id):
        return self._left_hand if hand_id == 'left' else self._right_hand
    
    def get_left_hand(self):
        return self._left_hand
    
    def get_right_hand(self):
        return self._right_hand
    
    def get_active_hands(self):
        active = []
        if self._left_hand.is_tracking:
            active.append(('left', self._left_hand))
        if self._right_hand.is_tracking:
            active.append(('right', self._right_hand))
        return active
    
    def get_slash_trajectory(self, hand_id):
        if hand_id == 'left':
            return self._left_slash_detector.trajectory
        else:
            return self._right_slash_detector.trajectory