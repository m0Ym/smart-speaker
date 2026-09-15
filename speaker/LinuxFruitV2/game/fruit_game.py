import math

from config import *
from game.models import Fruit, Bomb, Particle, SuperFruit, GameMode
from game.spawn_manager import SpawnManager
from game.collision import slice_collision
from game.assets import FruitAssets
from game.sound import SoundManager
from config import FRUIT_TEXTURE_MAP


class FruitGame:
    def __init__(self):
        self._fruits = []
        self._bombs = []
        self._particles = []
        self._super_fruits = []
        
        self._spawn_manager = SpawnManager()
        
        self._current_mode = GameMode.LIMITED_LIVES
        self._lives = INITIAL_LIVES
        
        self.score = 0
        self._combo = 1
        self.max_combo = 1
        
        self.is_running = False
        self.is_paused = False
        
        self.on_stats_changed = None
        self.on_toast = None
        self.on_game_over = None
        self.on_lives_changed = None
        self.on_sound = None
        
        self._fruit_colors = {
            'watermelon': {'main': (255, 100, 100), 'juice': (255, 50, 50)},
            'orange': {'main': (255, 165, 0), 'juice': (255, 140, 0)},
            'lemon': {'main': (255, 255, 0), 'juice': (200, 200, 0)},
            'lime': {'main': (0, 255, 0), 'juice': (0, 200, 0)},
            'berry': {'main': (255, 0, 255), 'juice': (200, 0, 200)}
        }
    
    @property
    def combo(self):
        return self._combo
    
    @combo.setter
    def combo(self, value):
        self._combo = value
        if self._combo > self.max_combo:
            self.max_combo = self._combo
    
    def initialize(self, width, height, mode=GameMode.LIMITED_LIVES):
        self.width = width
        self.height = height
        self._current_mode = mode
        self._spawn_manager.mode = mode
        
        self.reset()
    
    def start(self):
        self.is_running = True
        self.is_paused = False
    
    def pause(self):
        self.is_paused = True
    
    def resume(self):
        self.is_paused = False
    
    def reset(self):
        self.score = 0
        self.combo = 1
        self.max_combo = 1
        self._lives = INITIAL_LIVES
        self._fruits.clear()
        self._bombs.clear()
        self._particles.clear()
        self._super_fruits.clear()
        
        self._spawn_manager.mode = self._current_mode
        
        self._notify_stats_changed()
        if self.on_lives_changed:
            self.on_lives_changed(self._lives)
    
    def update(self, delta_time):
        if not self.is_running or self.is_paused:
            return
        
        self._spawn_manager.update(delta_time, len(self._fruits))
        
        if self._spawn_manager.should_spawn():
            self._spawn_objects()
            
            if self._spawn_manager.should_spawn_bomb():
                self._spawn_bomb()
        
        if self._spawn_manager.should_spawn_super():
            self._spawn_super_fruit()
        
        self._update_fruits(delta_time)
        self._update_bombs(delta_time)
        self._update_super_fruits(delta_time)
        self._update_particles(delta_time)
    
    def _spawn_objects(self):
        for _ in range(self._spawn_manager._fruits_per_spawn):
            if len(self._fruits) >= self._spawn_manager._max_fruits:
                break
            
            fruit_data = self._spawn_manager.generate_fruit()
            fruit = Fruit.create(
                fruit_data['type'],
                fruit_data['x'],
                fruit_data['y'],
                fruit_data['vx'],
                fruit_data['vy']
            )
            texture = FruitAssets.get_fruit_image(fruit_data['type'])
            fruit.texture = texture
            fruit.texture_name = FRUIT_TEXTURE_MAP.get(fruit_data['type'], {}).get('full')
            self._fruits.append(fruit)
    
    def _spawn_bomb(self):
        if len(self._bombs) >= 2:
            return
        
        bomb_data = self._spawn_manager.generate_bomb()
        bomb = Bomb.create(
            bomb_data['x'],
            bomb_data['y'],
            bomb_data['vx'],
            bomb_data['vy']
        )
        bomb.texture = FruitAssets.get_bomb_image()
        self._bombs.append(bomb)
    
    def _spawn_super_fruit(self):
        super_data = self._spawn_manager.generate_super_fruit()
        super_fruit = SuperFruit.create(
            super_data['x'],
            super_data['y'],
            super_data['vx'],
            super_data['vy']
        )
        super_fruit.texture = FruitAssets.get_super_fruit_image()
        self._super_fruits.append(super_fruit)
        
        if self.on_toast:
            self.on_toast("Super Fruit!")
    
    def handle_slash(self, slash_event):
        if not self.is_running or self.is_paused:
            return

        hit_fruits = slice_collision(slash_event, self._fruits)
        hit_bombs = slice_collision(slash_event, self._bombs)
        hit_super = slice_collision(slash_event, self._super_fruits)

        hit_something = False
        
        if hit_super:
            for super_fruit, point in hit_super:
                self._slice_super_fruit(super_fruit, point)
                hit_something = True
        
        if hit_bombs:
            for bomb, point in hit_bombs:
                self._slice_bomb(bomb)
                return
        
        if hit_fruits:
            for fruit, point in hit_fruits:
                if not fruit.is_sliced:
                    self._slice_fruit(fruit, point)
                    hit_something = True
        
        if not hit_something:
            self.combo = 1
            self._notify_stats_changed()
    
    def _slice_fruit(self, fruit, slice_point):
        fruit.is_sliced = True
        
        if self.on_sound:
            self.on_sound('slice')
        
        self.combo += 1
        self.score += BASE_SCORE * self.combo
        
        self._create_sliced_fruit_halves(fruit)
        self._create_particles(fruit, slice_point)
        
        if self.combo >= COMBO_THRESHOLD:
            if self.on_toast:
                self.on_toast(f"Nice! Combo x{self.combo}")
        
        self._notify_stats_changed()
    
    def _create_sliced_fruit_halves(self, fruit):
        half1 = fruit.create_half(-1)
        half2 = fruit.create_half(1)

        half1.texture = FruitAssets.get_sliced_fruit1(fruit.fruit_type)
        half2.texture = FruitAssets.get_sliced_fruit2(fruit.fruit_type)
        
        half1.texture_name = FRUIT_TEXTURE_MAP.get(fruit.fruit_type, {}).get('slice1')
        half2.texture_name = FRUIT_TEXTURE_MAP.get(fruit.fruit_type, {}).get('slice2')

        self._fruits.remove(fruit)
        self._fruits.append(half1)
        self._fruits.append(half2)
    
    def _slice_bomb(self, bomb):
        bomb.is_exploded = True
        
        if self.on_sound:
            self.on_sound('explode')
        
        if self._current_mode == GameMode.LIMITED_LIVES:
            self._lives -= 1
            if self.on_lives_changed:
                self.on_lives_changed(self._lives)
            
            self._bombs.remove(bomb)
            
            if self._lives <= 0:
                if self.on_toast:
                    self.on_toast("Bomb! Game Over!")
                if self.on_game_over:
                    self.on_game_over()
            else:
                if self.on_toast:
                    self.on_toast(f"Bomb! Lives left: {self._lives}")
        
        self._notify_stats_changed()
    
    def _slice_super_fruit(self, super_fruit, slice_point):
        super_fruit.hit_count += 1
        self.combo = super_fruit.hit_count
        
        if self.on_sound:
            self.on_sound('slice')
        
        self.score += SUPER_FRUIT_POINTS_PER_HIT
        
        if self.on_toast:
            self.on_toast(f"Super! Combo x{self.combo}")
        
        self._notify_stats_changed()
    
    def _create_particles(self, fruit, slice_point):
        color = self._fruit_colors.get(fruit.fruit_type, {'juice': (255, 50, 50)})['juice']
        
        for _ in range(20):
            particle = Particle.create(slice_point[0], slice_point[1], color)
            self._particles.append(particle)
    
    def _update_fruits(self, delta_time):
        for i in range(len(self._fruits) - 1, -1, -1):
            fruit = self._fruits[i]
            fruit.update(delta_time)
            
            if fruit.is_out_of_bounds(self.height):
                if not fruit.is_sliced:
                    self.combo = 1
                    if self.on_toast:
                        self.on_toast("Missed!")
                
                self._fruits.pop(i)
                self._notify_stats_changed()
    
    def _update_bombs(self, delta_time):
        for i in range(len(self._bombs) - 1, -1, -1):
            bomb = self._bombs[i]
            bomb.update(delta_time)
            
            if bomb.is_out_of_bounds(self.height):
                self._bombs.pop(i)
    
    def _update_super_fruits(self, delta_time):
        for i in range(len(self._super_fruits) - 1, -1, -1):
            super_fruit = self._super_fruits[i]
            super_fruit.update(delta_time, SUPER_FRUIT_SLOW_FACTOR)
            
            if not super_fruit.is_active:
                self._super_fruits.pop(i)
    
    def _update_particles(self, delta_time):
        for i in range(len(self._particles) - 1, -1, -1):
            particle = self._particles[i]
            particle.update(delta_time)
            
            if not particle.is_alive:
                self._particles.pop(i)
    
    def _notify_stats_changed(self):
        if self.on_stats_changed:
            self.on_stats_changed(self.score, self.combo)
    
    def get_fruits(self):
        return self._fruits
    
    def get_bombs(self):
        return self._bombs
    
    def get_super_fruits(self):
        return self._super_fruits
    
    def get_particles(self):
        return self._particles
    
    def get_lives(self):
        return self._lives