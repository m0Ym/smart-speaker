import math
import random

from config import SCALE


class Fruit:
    FRUIT_TYPES = ['watermelon', 'orange', 'lemon', 'lime', 'berry']
    
    DEFAULT_GRAVITY = 800.0 * SCALE
    SLICED_GRAVITY_MULTIPLIER = 1.2
    SLICED_SPEED_MULTIPLIER = 1.5
    
    FRUIT_COLORS = {
        'watermelon': (255, 107, 138),
        'orange': (255, 179, 71),
        'lemon': (255, 242, 117),
        'lime': (184, 255, 107),
        'berry': (126, 184, 255),
    }
    
    def __init__(self):
        self.fruit_type = ""
        
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.radius = 30.0 * SCALE
        self.rotation = 0.0
        self.spin = 0.0
        
        self.is_sliced = False
        self.is_half = False
        self._slice_side = 0
        self.gravity = self.DEFAULT_GRAVITY
        self.sliced_time = 0.0
        self.slice_direction = None
        self.mass = 1.0
        
        self.texture = None
        self.texture_name = None
        self.color = (255, 255, 255)
    
    def update(self, delta_time):
        effective_gravity = self.gravity
        
        if self.is_sliced and self.is_half:
            effective_gravity *= self.SLICED_GRAVITY_MULTIPLIER
        
        self.vy += effective_gravity * delta_time
        self.x += self.vx * delta_time
        self.y += self.vy * delta_time
        self.rotation += self.spin * delta_time
    
    def is_out_of_bounds(self, canvas_height):
        return self.y > canvas_height + self.radius * 2
    
    def slice(self, slice_direction):
        self.is_sliced = True
        self.is_half = False
        self.sliced_time = 0.0
        self.slice_direction = slice_direction
    
    def create_half(self, side):
        half = Fruit()
        half.fruit_type = self.fruit_type
        half.x = self.x + (side * 8 * SCALE)
        half.y = self.y
        half.vx = self.vx + (side * 60 * SCALE)
        half.vy = self.vy
        half.radius = self.radius * 0.75
        half.rotation = self.rotation
        half.spin = self.spin + (side * 1.0)
        half.is_sliced = True
        half.is_half = True
        half._slice_side = side
        half.gravity = self.gravity
        half.mass = self.mass * 0.5
        half.texture = self.texture
        half.texture_name = self.texture_name
        half.color = self.color
        
        return half
    
    @classmethod
    def create(cls, fruit_type, x, y, vx, vy):
        fruit = cls()
        fruit.fruit_type = fruit_type
        fruit.x = x
        fruit.y = y
        fruit.vx = vx
        fruit.vy = vy
        fruit.spin = (random.random() - 0.5) * 2.0
        fruit.color = cls.FRUIT_COLORS.get(fruit_type, (255, 255, 255))
        
        if fruit_type == 'watermelon':
            fruit.radius = 35.0 * SCALE
            fruit.mass = 1.2
        elif fruit_type == 'orange':
            fruit.radius = 28.0 * SCALE
            fruit.mass = 1.0
        elif fruit_type == 'lemon':
            fruit.radius = 25.0 * SCALE
            fruit.mass = 0.9
        elif fruit_type == 'lime':
            fruit.radius = 26.0 * SCALE
            fruit.mass = 0.95
        elif fruit_type == 'berry':
            fruit.radius = 22.0 * SCALE
            fruit.mass = 0.7
        
        return fruit


class Bomb:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.radius = 28.0 * SCALE
        self.rotation = 0.0
        self.gravity = 800.0 * SCALE
        self.is_exploded = False
        self.texture = None
    
    def update(self, delta_time):
        self.vy += self.gravity * delta_time
        self.x += self.vx * delta_time
        self.y += self.vy * delta_time
    
    def is_out_of_bounds(self, canvas_height):
        return self.y > canvas_height + self.radius
    
    @classmethod
    def create(cls, x, y, vx, vy):
        bomb = cls()
        bomb.x = x
        bomb.y = y
        bomb.vx = vx
        bomb.vy = vy
        return bomb


class Particle:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.life = 1.0
        self.max_life = 1.0
        self.color = (255, 255, 255)
        self.size = 5.0 * SCALE
        self.gravity = 300.0 * SCALE
    
    def update(self, delta_time):
        self.vy += self.gravity * delta_time
        self.x += self.vx * delta_time
        self.y += self.vy * delta_time
        self.life -= delta_time
    
    @property
    def is_alive(self):
        return self.life > 0
    
    @classmethod
    def create(cls, x, y, color, speed=100.0):
        particle = cls()
        particle.x = x
        particle.y = y
        particle.color = color
        
        angle = random.uniform(0, 2 * math.pi)
        speed_val = random.uniform(50, speed) * SCALE
        particle.vx = math.cos(angle) * speed_val
        particle.vy = math.sin(angle) * speed_val
        
        particle.size = random.uniform(3 * SCALE, 8 * SCALE)
        particle.life = random.uniform(0.3, 0.8)
        particle.max_life = particle.life
        
        return particle


class SuperFruit:
    NORMAL_GRAVITY = 300.0 * SCALE
    SLOW_GRAVITY = 60.0 * SCALE
    SLOW_FALL_DURATION = 10.0
    
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.radius = 78.0 * SCALE
        self.rotation = 0.0
        self.spin = 0.0
        
        self.is_falling = False
        self.is_slow_falling = False
        self.is_active = True
        
        self.hit_count = 0
        self.slow_fall_timer = 0.0
        
        self.texture = None
    
    @classmethod
    def create(cls, x, y, vx, vy, radius=None):
        fruit = cls()
        fruit.x = x
        fruit.y = y
        fruit.vx = vx
        fruit.vy = vy
        fruit.radius = radius if radius is not None else 78.0 * SCALE
        fruit.spin = (random.random() - 0.5) * 2.0
        return fruit
    
    def update(self, delta_time, slow_factor=3.0):
        if not self.is_active:
            return
        
        if self.is_slow_falling:
            self.vy += self.SLOW_GRAVITY * delta_time
            self.slow_fall_timer -= delta_time
            
            if self.slow_fall_timer <= 0:
                self.is_slow_falling = False
        else:
            self.vy += self.NORMAL_GRAVITY * delta_time
            
            if not self.is_falling and self.vy > 0:
                self.is_falling = True
                self.is_slow_falling = True
                self.slow_fall_timer = self.SLOW_FALL_DURATION
                self.vy = self.vy / slow_factor
        
        self.x += self.vx * delta_time
        self.y += self.vy * delta_time
        self.rotation += self.spin * delta_time
        
        if self.y - self.radius > 1000:
            self.is_active = False
    
    def is_out_of_bounds(self, canvas_height):
        return self.y > canvas_height + self.radius


class GameMode:
    LIMITED_LIVES = "limited_lives"
    SLASH_MODE = "slash_mode"