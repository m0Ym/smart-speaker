import os
import pygame

from config import FRUIT_TEXTURE_MAP


class FruitAssets:
    _fruit_images = {}
    _fruit_sliced1_images = {}
    _fruit_sliced2_images = {}
    _bomb_image = None
    _flash_image = None
    _background_image = None
    _initialized = False
    
    @classmethod
    def initialize(cls, resources_dir):
        if cls._initialized:
            return
        
        cls._fruit_images = {}
        cls._fruit_sliced1_images = {}
        cls._fruit_sliced2_images = {}
        
        images_dir = os.path.join(resources_dir, "images")
        fruit_dir = os.path.join(images_dir, "fruit")
        
        for fruit_name, textures in FRUIT_TEXTURE_MAP.items():
            full_path = os.path.join(fruit_dir, textures["full"])
            slice1_path = os.path.join(fruit_dir, textures["slice1"])
            slice2_path = os.path.join(fruit_dir, textures["slice2"])
            
            cls._fruit_images[fruit_name] = cls._load_image(full_path)
            cls._fruit_sliced1_images[fruit_name] = cls._load_image(slice1_path)
            cls._fruit_sliced2_images[fruit_name] = cls._load_image(slice2_path)
        
        cls._bomb_image = cls._load_image(os.path.join(fruit_dir, "boom.png"))
        cls._flash_image = cls._load_image(os.path.join(images_dir, "flash.png"))
        cls._background_image = cls._load_image(os.path.join(images_dir, "background.jpg"))
        
        cls._initialized = True
    
    @classmethod
    def _load_image(cls, path):
        if os.path.exists(path):
            try:
                img = pygame.image.load(path).convert_alpha()
                result = pygame.transform.scale(img, (64, 64))
                print(f"[Asset] Loaded image: {path} ({result.get_size()})")
                return result
            except Exception as e:
                print(f"[Asset] Failed to load image {path}: {e}")
                surf = pygame.Surface((64, 64), pygame.SRCALPHA)
                surf.fill((128, 128, 128, 128))
                return surf
        else:
            print(f"[Asset] Image not found: {path}")
            surf = pygame.Surface((64, 64), pygame.SRCALPHA)
            surf.fill((128, 128, 128, 128))
            return surf
    
    @classmethod
    def get_fruit_image(cls, name):
        return cls._fruit_images.get(name)
    
    @classmethod
    def get_sliced_fruit1(cls, name):
        return cls._fruit_sliced1_images.get(name)
    
    @classmethod
    def get_sliced_fruit2(cls, name):
        return cls._fruit_sliced2_images.get(name)
    
    @classmethod
    def get_bomb_image(cls):
        return cls._bomb_image
    
    @classmethod
    def get_flash_image(cls):
        return cls._flash_image
    
    @classmethod
    def get_background_image(cls):
        return cls._background_image
    
    @classmethod
    def get_super_fruit_image(cls):
        return cls._flash_image