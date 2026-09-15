from __future__ import annotations
from typing import Any, Dict, Optional, Type
from ..utils.logger import logger

from ..core.factory import Factory
from .base import BaseSkill, SkillResult
from .impl import (
    WeatherSkill,
    MusicSkill,
    AlarmSkill,
    JokeSkill,
    ChatSkill,
    SmartHomeSkill,
)
from .gesture_control import GestureControlSkill
from .system_command import SystemCommandSkill
from .fruit_ninja import FruitNinjaSkill


class SkillFactory(Factory[BaseSkill]):
    def __init__(self) -> None:
        super().__init__()
        self._register_defaults()
        # 注入上下文：供 skill 通过依赖注入获取全局实例
        self._context: Dict[str, Any] = {}

    def set_context(self, **kwargs: Any) -> None:
        """注入 skill 所需的全局依赖（如全局 MusicPlayer）"""
        self._context.update(kwargs)
        logger.info(f"SkillFactory context updated: {list(kwargs.keys())}")

    def _register_defaults(self) -> None:
        self.register("weather", WeatherSkill)
        self.register("music", MusicSkill)
        self.register("alarm", AlarmSkill)
        self.register("joke", JokeSkill)
        self.register("chat", ChatSkill)
        self.register("smarthome", SmartHomeSkill)
        self.register("fruit_ninja", FruitNinjaSkill)
        self.register("gesture", GestureControlSkill)
        self.register("system_command", SystemCommandSkill)
        logger.info("Default skills registered")

    def create_skill(self, name: str, *args: Any, **kwargs: Any) -> Optional[BaseSkill]:
        return self.create(name, *args, **kwargs)

    def create_all(self) -> Dict[str, BaseSkill]:
        skills = {}
        for name in self.available:
            skill = self._create_with_context(name)
            if skill:
                skills[name] = skill
        return skills

    def _create_with_context(self, name: str) -> Optional[BaseSkill]:
        """根据 skill 类型与注入上下文构造实例，避免重复创建全局依赖"""
        if name not in self._registry:
            logger.warning(f"SkillFactory: key not found - {name}")
            return None
        cls = self._registry[name]
        if cls is MusicSkill:
            music_player = self._context.get("music_player")
            if music_player is not None:
                return cls(music_player=music_player)
        return cls()
