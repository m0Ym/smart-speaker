import random

from config import SCREEN_WIDTH, SCREEN_HEIGHT, BOMB_SPAWN_CHANCE, SCALE


class SpawnManager:
    FRUIT_TYPES = ['watermelon', 'orange', 'lemon', 'lime', 'berry']
    
    def __init__(self):
        self._spawn_timer = 0.0
        self._spawn_interval = 1.0
        self._super_fruit_timer = 0.0
        self._super_fruit_interval = 30.0
        self._fruit_count = 0
        self._max_fruits = 15
        self._fruits_per_spawn = 3
        self._mode = 'limited_lives'
    
    @property
    def mode(self):
        return self._mode
    
    @mode.setter
    def mode(self, value):
        self._mode = value
        if value == 'slash_mode':
            self._spawn_interval = 0.3
            self._max_fruits = 30
            self._fruits_per_spawn = 9
        else:
            self._spawn_interval = 1.0
            self._max_fruits = 15
            self._fruits_per_spawn = 3
    
    def update(self, delta_time, fruit_count):
        self._spawn_timer += delta_time
        self._super_fruit_timer += delta_time
        self._fruit_count = fruit_count
    
    def should_spawn(self):
        if self._fruit_count >= self._max_fruits:
            return False
        
        if self._spawn_timer >= self._spawn_interval:
            self._spawn_timer = 0.0
            return True
        
        return False
    
    def should_spawn_bomb(self):
        if self._mode != 'limited_lives':
            return False
        
        prob = self.get_spawn_probability()
        if prob['bomb'] > 0:
            return random.random() < prob['bomb']
        
        return False
    
    def should_spawn_super(self):
        if self._super_fruit_timer >= self._super_fruit_interval:
            self._super_fruit_timer = 0.0
            return True
        return False
    
    def generate_fruit(self):
        fruit_type = random.choice(self.FRUIT_TYPES)
        
        x = random.uniform(SCREEN_WIDTH * 0.1, SCREEN_WIDTH * 0.9)
        y = SCREEN_HEIGHT + 50 * SCALE
        
        vy = -(650 + random.random() * 250) * SCALE
        vx = (random.random() - 0.5) * 320 * SCALE
        
        return {
            'type': fruit_type,
            'x': x,
            'y': y,
            'vx': vx,
            'vy': vy
        }
    
    def generate_bomb(self):
        x = random.uniform(SCREEN_WIDTH * 0.2, SCREEN_WIDTH * 0.8)
        y = SCREEN_HEIGHT + 28 * SCALE
        
        vy = -(520 + random.random() * 180) * SCALE
        vx = (random.random() - 0.5) * 260 * SCALE
        
        return {
            'x': x,
            'y': y,
            'vx': vx,
            'vy': vy
        }
    
    def generate_super_fruit(self):
        x = 100 * SCALE + random.random() * (SCREEN_WIDTH - 200 * SCALE)
        y = SCREEN_HEIGHT + 100 * SCALE
        
        vy = -(400 + random.random() * 100) * SCALE
        vx = (random.random() - 0.5) * 100 * SCALE
        
        return {
            'x': x,
            'y': y,
            'vx': vx,
            'vy': vy
        }
    
    def get_spawn_probability(self):
        if self._mode == 'slash_mode':
            return {'fruit': 1.0, 'bomb': 0.0}
        
        return {'fruit': 1.0 - BOMB_SPAWN_CHANCE, 'bomb': BOMB_SPAWN_CHANCE}