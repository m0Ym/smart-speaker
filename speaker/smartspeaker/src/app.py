from __future__ import annotations
import os
import sys
import time
import threading
from typing import Optional
from .utils.logger import logger

from .config import AppConfig
from .core.message_bus import MessageBus, Event, EventType
from .core.websocket_broadcaster import WebSocketBroadcaster
from .audio.processor import AudioProcessor
from .vision.depth import VisionDepth
from .nlp.processor import NLPProcessor
from .nlp.tool_executor import ToolExecutor
from .dialog.manager import DialogManager
from .ui.manager import UIManager
from .monitoring.sla import SLAMonitor


class SmartSpeakerApp:
    def __init__(self, config_path: Optional[str] = None) -> None:
        self._config = AppConfig.load(config_path)
        self._bus = MessageBus()
        self._running = False
        self._start_time = 0.0
        # 主程序关闭回调：当收到语音退出指令时调用，让 main.py 的主循环退出
        self.on_shutdown_request: Optional[callable] = None

        self._audio_processor: Optional[AudioProcessor] = None
        self._vision_depth: Optional[VisionDepth] = None
        self._nlp_processor: Optional[NLPProcessor] = None
        self._tool_executor: Optional[ToolExecutor] = None
        self._dialog_manager: Optional[DialogManager] = None
        self._ui_manager: Optional[UIManager] = None
        self._sla_monitor: Optional[SLAMonitor] = None
        self._websocket_broadcaster: Optional[WebSocketBroadcaster] = None

        self._setup_logging()
        self._init_components()
        logger.info(f"SmartSpeakerApp initialized - {self._config.system.device_name}")

    def _setup_logging(self) -> None:
        import logging
        level = self._config.system.log_level

        log_dir = os.path.join(self._config.system.data_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)

        file_handler = logging.FileHandler(os.path.join(log_dir, "app.log"))
        file_handler.setLevel(getattr(logging, level, logging.INFO))
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        logger._logger.addHandler(file_handler)

    def _init_components(self) -> None:
        self._sla_monitor = SLAMonitor(self._bus, self._config.system)
        self._audio_processor = AudioProcessor(
            self._config.audio, 
            self._bus, 
            music_dir=self._config.system.music_dir
        )
        self._vision_depth = VisionDepth(self._config.vision, self._bus) if self._config.vision.enabled else None
        self._nlp_processor = NLPProcessor(self._config.nlp, self._bus)
        self._tool_executor = ToolExecutor(self._bus)
        self._nlp_processor.set_tool_executor(self._tool_executor)
        self._dialog_manager = DialogManager(self._bus)
        # 注入全局依赖：让 MusicSkill 复用 AudioProcessor 的全局 MusicPlayer
        if self._audio_processor and getattr(self._audio_processor, "_music_player", None) is not None:
            self._dialog_manager._skill_factory.set_context(
                music_player=self._audio_processor._music_player
            )
            # 重新创建 skills，让 MusicSkill 拿到注入实例
            self._dialog_manager._init_skills()
        self._ui_manager = UIManager(self._config.ui, self._bus)

        self._dialog_manager.attach(self._ui_manager)
        self._dialog_manager.attach(self._nlp_processor)

    def start(self, enable_microphone: bool = True) -> None:
        if self._running:
            return

        self._running = True
        self._start_time = time.time()

        logger.info("=" * 60)
        logger.info(f"  {self._config.system.device_name} 启动中...")
        logger.info("=" * 60)

        if self._audio_processor:
            self._audio_processor.start(start_microphone=enable_microphone)
            logger.info(f"  [OK] 音频模块 - ASR策略: {self._audio_processor.current_asr_strategy}, 麦克风: {'开' if enable_microphone else '关'}")

        if self._vision_depth:
            self._vision_depth.start()
            logger.info(f"  [OK] 视觉模块 - {self._config.vision.camera_width}x{self._config.vision.camera_height} @ {self._config.vision.camera_fps}fps")
        else:
            logger.info(f"  [SKIP] 视觉模块 - 未启用 (设置 VISION_ENABLED=true 启用)")

        if self._nlp_processor:
            self._nlp_processor.start()
            logger.info(f"  [OK] NLP模块 - 离线模式: {self._config.nlp.offline_mode}")

        if self._tool_executor:
            self._tool_executor.start()
            logger.info(f"  [OK] 工具执行器 - 可用工具: {len(self._tool_executor.get_tools_descriptions())}个")

        if self._dialog_manager:
            self._dialog_manager.start()
            logger.info(f"  [OK] 对话管理 - 可用技能: {len(self._dialog_manager.available_skills)}个")

        if self._ui_manager:
            self._ui_manager.start()
            logger.info(f"  [OK] UI模块 - 主屏+电子墨水副屏")

        self._websocket_broadcaster = WebSocketBroadcaster(self._bus)
        self._start_websocket_server()
        logger.info(f"  [OK] WebSocket广播器 - ws://localhost:8765")

        # 订阅系统状态事件：处理语音退出指令（DialogManager 发出 shutdown 事件）
        self._bus.subscribe(EventType.SYSTEM_STATUS, self._on_system_status, "app_shutdown_handler")

        self._bus.publish(
            Event(
                event_type=EventType.SYSTEM_STATUS,
                data={"status": "started", "device": self._config.system.device_name},
                source="SmartSpeakerApp",
            )
        )

        startup_time = (time.time() - self._start_time) * 1000
        logger.info("=" * 60)
        logger.info(f"  启动完成! 耗时: {startup_time:.1f}ms")
        logger.info(f"  唤醒词: {self._config.audio.wake_word}")
        logger.info(f"  WebSocket: ws://localhost:8765")
        logger.info("=" * 60)

        if self._audio_processor:
            # 启动问候语在守护线程中执行，带 10 秒超时，避免阻塞主流程
            self._speak_startup_greeting()

    def _speak_startup_greeting(self) -> None:
        """守护线程中播放启动问候语，10 秒超时"""
        def _greeting():
            try:
                if self._audio_processor:
                    self._audio_processor.speak("你好！我是智能音箱小智，很高兴为您服务。")
            except Exception as e:
                logger.warning(f"Startup greeting failed: {e}")

        t = threading.Thread(target=_greeting, daemon=True)
        t.start()
        t.join(timeout=10.0)
        if t.is_alive():
            logger.warning("Startup greeting timeout (>10s), continuing without waiting")

    def _start_websocket_server(self) -> None:
        def _websocket_thread():
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._websocket_broadcaster.start())
                loop.run_forever()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"WebSocket server error: {e}")
            finally:
                loop.close()
        
        self._websocket_thread = threading.Thread(target=_websocket_thread, daemon=True)
        self._websocket_thread.start()

    def _on_system_status(self, event: Event) -> None:
        """处理系统状态事件，特别是语音退出指令"""
        status = event.data.get("status", "")
        source = event.data.get("source", "")

        if status == "shutdown":
            logger.info(f"[App] 收到关闭指令 (来源: {source})，准备退出系统")
            # 先执行应用自身的清理
            try:
                self.stop()
            except Exception as e:
                logger.error(f"[App] stop() 异常: {e}")
            # 通知主程序退出主循环
            if self.on_shutdown_request is not None:
                try:
                    self.on_shutdown_request()
                except Exception as e:
                    logger.error(f"[App] on_shutdown_request 回调异常: {e}")
            # 兜底：如果回调没有效果，3 秒后强制退出
            def _force_exit():
                import time as _time
                _time.sleep(3.0)
                logger.warning("[App] 优雅关闭超时，强制退出进程")
                os._exit(0)
            threading.Thread(target=_force_exit, daemon=True).start()

    def stop(self) -> None:
        if not self._running:
            return

        logger.info("正在关闭系统...")

        self._bus.publish(
            Event(
                event_type=EventType.SYSTEM_STATUS,
                data={"status": "shutdown"},
                source="SmartSpeakerApp",
            )
        )

        if self._ui_manager:
            self._ui_manager.stop()
        if self._dialog_manager:
            self._dialog_manager.stop()
        if self._tool_executor:
            self._tool_executor.stop()
        if self._nlp_processor:
            self._nlp_processor.stop()
        if self._vision_depth:
            self._vision_depth.stop()
        if self._audio_processor:
            self._audio_processor.stop()

        if self._websocket_broadcaster:
            try:
                self._websocket_broadcaster.stop_sync()
                logger.info("  [OK] WebSocket广播器已停止")
            except Exception as e:
                logger.warning(f"WebSocket停止异常: {e}")

        if hasattr(self, '_websocket_thread') and self._websocket_thread.is_alive():
            self._websocket_thread.join(timeout=3.0)
            if self._websocket_thread.is_alive():
                logger.warning("WebSocket thread did not terminate within timeout")

        self._running = False

        uptime = time.time() - self._start_time
        logger.info(f"系统已关闭，运行时间: {uptime:.1f}秒")

    def simulate_wake_word(self) -> None:
        import numpy as np

        if not self._audio_processor:
            return

        logger.info(">>> 模拟唤醒词检测")
        chunk_size = self._config.audio.chunk_size

        silence = np.zeros(chunk_size, dtype=np.float32)
        for _ in range(5):
            self._audio_processor.processAudio(silence)

        wake_signal = np.random.randn(chunk_size).astype(np.float32) * 0.3
        for _ in range(5):
            self._audio_processor.processAudio(wake_signal)

    def simulate_user_input(self, text: str) -> None:
        if not self._bus:
            return

        # 防御性检查：空文本不处理
        if not text or not text.strip():
            return

        logger.info(f">>> 用户说: {text}")
        # 先发送 DIALOG_START 建立会话（与浏览器/语音模式一致），再发送转写结果
        self._bus.publish(
            Event(
                event_type=EventType.DIALOG_START,
                data={"trigger": "text_input", "text": text},
                source="Simulator",
                priority=3,
            )
        )
        self._bus.publish(
            Event(
                event_type=EventType.NLP_TRANSCRIBE_DONE,
                data={"text": text, "duration": 2.0},
                source="Simulator",
                priority=3,
            )
        )

    def get_status(self) -> dict:
        sla = self._sla_monitor.get_summary() if self._sla_monitor else {}
        return {
            "running": self._running,
            "uptime": time.time() - self._start_time if self._running else 0,
            "device_name": self._config.system.device_name,
            "device_id": self._config.system.device_id,
            "dialog_state": self._dialog_manager.current_state.value if self._dialog_manager else "idle",
            "available_skills": self._dialog_manager.available_skills if self._dialog_manager else [],
            "asr_strategy": self._audio_processor.current_asr_strategy if self._audio_processor else None,
            "sla": sla,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def message_bus(self) -> MessageBus:
        return self._bus

    @property
    def audio(self) -> Optional[AudioProcessor]:
        return self._audio_processor

    @property
    def vision(self) -> Optional[VisionDepth]:
        return self._vision_depth

    @property
    def nlp(self) -> Optional[NLPProcessor]:
        return self._nlp_processor

    @property
    def dialog(self) -> Optional[DialogManager]:
        return self._dialog_manager

    @property
    def ui(self) -> Optional[UIManager]:
        return self._ui_manager

    @property
    def monitor(self) -> Optional[SLAMonitor]:
        return self._sla_monitor
