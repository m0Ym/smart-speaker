import os
import pygame

from config import SOUND_VOLUME


class SoundManager:
    _sound_paths = {}
    _sounds = {}
    _initialized = False
    
    @classmethod
    def initialize(cls, resources_dir):
        if cls._initialized:
            return
        
        cls._sound_paths = {}
        cls._sounds = {}
        
        sound_dir = os.path.join(resources_dir, "sound")
        
        cls._sound_paths["slice"] = cls._get_sound_path(sound_dir, "splatter")
        cls._sound_paths["explode"] = cls._get_sound_path(sound_dir, "boom")
        cls._sound_paths["start"] = cls._get_sound_path(sound_dir, "start")
        cls._sound_paths["gameover"] = cls._get_sound_path(sound_dir, "over")
        
        for name, path in cls._sound_paths.items():
            if path:
                try:
                    sound = pygame.mixer.Sound(path)
                    sound.set_volume(SOUND_VOLUME)
                    cls._sounds[name] = sound
                except Exception as e:
                    print(f"Failed to load sound {name}: {e}")
        
        cls._initialized = True
    
    @classmethod
    def _get_sound_path(cls, sound_dir, name):
        mp3_path = os.path.join(sound_dir, f"{name}.mp3")
        ogg_path = os.path.join(sound_dir, f"{name}.ogg")
        
        if os.path.exists(mp3_path):
            return mp3_path
        if os.path.exists(ogg_path):
            return ogg_path
        
        return None
    
    @classmethod
    def play(cls, sound_name):
        if not cls._initialized:
            return
        
        sound = cls._sounds.get(sound_name)
        if sound:
            try:
                sound.play()
            except Exception as e:
                print(f"Failed to play sound {sound_name}: {e}")
    
    @classmethod
    def play_slice(cls):
        cls.play("slice")
    
    @classmethod
    def play_explode(cls):
        cls.play("explode")
    
    @classmethod
    def play_start(cls):
        cls.play("start")
    
    @classmethod
    def play_game_over(cls):
        cls.play("gameover")