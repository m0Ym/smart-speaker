"""
仪表盘事件发布器 - DashboardEventPublisher
==========================================
这是 smartspeakersrc（语音核心）唯一需要知道的接口。
语音核心只需 import 并调用 send_status / send_transcript / send_response_chunk 等方法，
内部自动通过 WebSocket 广播给所有已连接的仪表盘客户端。

使用示例（在 smartspeakersrc 任意模块中）：
    from smartspeaker.dashboard.ipc_bridge import DashboardEventPublisher
    pub = DashboardEventPublisher.get_instance()
    pub.send_status("listening")
    pub.send_transcript("播放音乐", "user")
"""

import json
import asyncio
from dataclasses import dataclass
from typing import Optional, Literal, Set, Any


@dataclass
class DashboardEvent:
    """仪表盘事件协议"""
    event_type: Literal[
        "status", "transcript", "response_chunk", "response_done",
        "telemetry", "skill", "music",
    ]
    payload: dict


class DashboardEventPublisher:
    """
    单例模式事件发布器。
    语音核心通过此类的实例方法发送事件，不直接操作 WebSocket。
    """
    _instance: Optional["DashboardEventPublisher"] = None

    @classmethod
    def get_instance(cls) -> "DashboardEventPublisher":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        # 存储所有已连接的 WebSocket 客户端（由 dashboard server 注入）
        self._ws_clients: Set[Any] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """由服务端调用，注入事件循环，用于异步发送"""
        self._loop = loop

    def register_ws_client(self, client) -> None:
        """注册一个 WebSocket 客户端连接"""
        self._ws_clients.add(client)

    def unregister_ws_client(self, client) -> None:
        """注销一个 WebSocket 客户端连接"""
        self._ws_clients.discard(client)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 以下为语音核心直接调用的便捷方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def send_status(
        self,
        status: Literal["idle", "listening", "processing", "speaking", "error"],
        detail: Optional[str] = None,
    ) -> None:
        """发送助手状态变化 —— 控制中央光环的四种光影特效"""
        self._broadcast({
            "type": "status",
            "status": status,
            "detail": detail or "",
        })

    def send_transcript(
        self,
        text: str,
        speaker: Literal["user", "assistant"] = "user",
    ) -> None:
        """
        发送对话文本到终端流
        speaker="user"    → 绿色文字（用户语音识别结果）
        speaker="assistant" → 青色文字（AI回复）
        """
        self._broadcast({
            "type": "transcript",
            "text": text,
            "speaker": speaker,
        })

    def send_response_chunk(self, text: str) -> None:
        """发送 LLM 流式回复片段 —— 触发终端打字机逐字特效"""
        self._broadcast({
            "type": "response_chunk",
            "text": text,
        })

    def send_response_done(self, full_text: str = "") -> None:
        """LLM 回复完成"""
        self._broadcast({
            "type": "response_done",
            "text": full_text,
        })

    def send_telemetry(
        self,
        cpu_percent: float,
        memory_percent: float,
        temperature_c: float,
        wifi_rssi: int = -50,
    ) -> None:
        """发送系统遥测数据 —— 左侧仪表盘数值更新"""
        self._broadcast({
            "type": "telemetry",
            "cpu": round(cpu_percent, 1),
            "memory": round(memory_percent, 1),
            "temperature": round(temperature_c, 1),
            "wifi_rssi": wifi_rssi,
        })

    def send_skill(self, skill_name: str, params: Optional[dict] = None) -> None:
        """技能触发通知"""
        self._broadcast({
            "type": "skill",
            "name": skill_name,
            "params": params or {},
        })

    def send_music(self, action: str, song_name: str = "", artist: str = "") -> None:
        """音乐播放状态"""
        self._broadcast({
            "type": "music",
            "action": action,
            "song_name": song_name,
            "artist": artist,
        })

    def _broadcast(self, message: dict) -> None:
        """内部：通过 WebSocket 广播给所有已连接的仪表盘客户端"""
        if not self._ws_clients:
            return

        text = json.dumps(message, ensure_ascii=False)
        dead = set()

        for client in self._ws_clients:
            try:
                # 如果客户端有 send_text 方法（FastAPI WebSocket）
                if hasattr(client, "send_text"):
                    # 异步发送，不阻塞语音核心线程
                    if self._loop and self._loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            client.send_text(text), self._loop
                        )
                    else:
                        # 无事件循环时同步发送（兜底）
                        import asyncio
                        asyncio.run(client.send_text(text))
                # 如果客户端有 send 方法（通用 WebSocket）
                elif hasattr(client, "send"):
                    if self._loop and self._loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            client.send(text), self._loop
                        )
                    else:
                        import asyncio
                        asyncio.run(client.send(text))
            except Exception:
                dead.add(client)

        self._ws_clients -= dead
