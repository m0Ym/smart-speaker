import os
import json

from config import SCORE_SAVE_PATH
from game.models import GameMode


class ScoreData:
    def __init__(self):
        self.limited_lives_high_score = 0
        self.slash_mode_high_score = 0
        self.limited_lives_max_combo = 0
        self.slash_mode_max_combo = 0


class ScoreManager:
    _score_data = None
    _save_path = SCORE_SAVE_PATH
    _initialized = False
    
    @classmethod
    def _initialize(cls):
        if cls._initialized:
            return
        
        cls._score_data = ScoreData()
        
        if os.path.exists(cls._save_path):
            try:
                with open(cls._save_path, "r") as f:
                    data = json.load(f)
                    cls._score_data.limited_lives_high_score = data.get("limited_lives_high_score", 0)
                    cls._score_data.slash_mode_high_score = data.get("slash_mode_high_score", 0)
                    cls._score_data.limited_lives_max_combo = data.get("limited_lives_max_combo", 0)
                    cls._score_data.slash_mode_max_combo = data.get("slash_mode_max_combo", 0)
            except Exception as e:
                print(f"Failed to load score data: {e}")
                cls._score_data = ScoreData()
        
        cls._initialized = True
    
    @classmethod
    def get_high_score(cls, mode):
        cls._initialize()
        
        if mode == GameMode.LIMITED_LIVES:
            return cls._score_data.limited_lives_high_score
        else:
            return cls._score_data.slash_mode_high_score
    
    @classmethod
    def get_max_combo(cls, mode):
        cls._initialize()
        
        if mode == GameMode.LIMITED_LIVES:
            return cls._score_data.limited_lives_max_combo
        else:
            return cls._score_data.slash_mode_max_combo
    
    @classmethod
    def update_high_score(cls, mode, score, combo):
        cls._initialize()
        
        is_new_record = False
        
        if mode == GameMode.LIMITED_LIVES:
            if score > cls._score_data.limited_lives_high_score:
                cls._score_data.limited_lives_high_score = score
                is_new_record = True
            if combo > cls._score_data.limited_lives_max_combo:
                cls._score_data.limited_lives_max_combo = combo
                is_new_record = True
        else:
            if score > cls._score_data.slash_mode_high_score:
                cls._score_data.slash_mode_high_score = score
                is_new_record = True
            if combo > cls._score_data.slash_mode_max_combo:
                cls._score_data.slash_mode_max_combo = combo
                is_new_record = True
        
        if is_new_record:
            cls._save()
        
        return is_new_record
    
    @classmethod
    def _save(cls):
        try:
            data = {
                "limited_lives_high_score": cls._score_data.limited_lives_high_score,
                "slash_mode_high_score": cls._score_data.slash_mode_high_score,
                "limited_lives_max_combo": cls._score_data.limited_lives_max_combo,
                "slash_mode_max_combo": cls._score_data.slash_mode_max_combo,
            }
            with open(cls._save_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save score data: {e}")
    
    @classmethod
    def reset(cls):
        cls._initialize()
        cls._score_data = ScoreData()
        cls._save()