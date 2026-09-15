from __future__ import annotations
import threading
from typing import Optional, Dict, Any, List
from ..utils import logger


class MusicPlayerManager:
    """全局单例音乐播放器管理器，确保所有模块共享同一个 MusicPlayer 实例"""

    _instance: Optional['MusicPlayerManager'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._player = None
                    cls._instance._init_lock = threading.Lock()
        return cls._instance

    def get_player(self):
        """获取全局 MusicPlayer 实例（懒加载）"""
        if self._player is None:
            with self._init_lock:
                if self._player is None:
                    from .music_player import MusicPlayer
                    self._player = MusicPlayer()
                    logger.info("[MusicPlayerManager] 全局 MusicPlayer 实例已创建")
        return self._player

    def get_status(self) -> Dict[str, Any]:
        """获取当前音乐播放状态"""
        player = self.get_player()
        try:
            song = player.current_song
            return {
                "is_playing": getattr(player, '_is_playing', False),
                "is_paused": getattr(player, '_is_paused', False),
                "current_song": song or {},
                "song_index": getattr(player, '_current_song_index', -1),
                "volume": getattr(player, '_volume', 80),
                "position": round(getattr(player, '_current_position', 0), 1),
                "duration": round(getattr(player, '_current_duration', 0), 1),
                "library_count": getattr(player._library, 'count', 0) if hasattr(player, '_library') else 0,
            }
        except Exception as e:
            logger.error(f"[MusicPlayerManager] 获取状态失败: {e}")
            return {
                "is_playing": False,
                "is_paused": False,
                "current_song": {},
                "song_index": -1,
                "volume": 80,
                "position": 0,
                "duration": 0,
                "library_count": 0,
            }

    def get_song_list(self) -> List[Dict[str, Any]]:
        """获取音乐库所有歌曲"""
        player = self.get_player()
        try:
            songs = player._library.songs if hasattr(player, '_library') else []
            return [
                {
                    "title": s.get("title", ""),
                    "artist": s.get("artist", ""),
                    "filename": s.get("filename", ""),
                    "path": s.get("path", ""),
                    "size": s.get("size", 0),
                }
                for s in songs
            ]
        except Exception as e:
            logger.error(f"[MusicPlayerManager] 获取歌曲列表失败: {e}")
            return []


_manager_instance: Optional[MusicPlayerManager] = None


def get_player_manager() -> MusicPlayerManager:
    """获取全局播放器管理器单例"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = MusicPlayerManager()
    return _manager_instance