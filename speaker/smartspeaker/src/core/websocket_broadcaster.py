import asyncio
import json
import threading
import time
import platform
import websockets
from typing import Dict, List, Optional, Any
from ..core.message_bus import MessageBus, Event, EventType
from ..core.state_machine import SystemState
from ..utils.logger import logger


class WebSocketBroadcaster:
    """WebSocket状态广播器"""

    def __init__(self, message_bus: MessageBus, host: str = "0.0.0.0", port: int = 8765):
        self.message_bus = message_bus
        self.host = host
        self.port = port
        self.server = None
        self.clients: Dict[str, websockets.WebSocketServerProtocol] = {}
        self.running = False
        self.broadcast_thread = None
        self._clients_lock = threading.RLock()
        self._event_loop = None
        self._broadcast_queue: Optional[asyncio.Queue[Dict[str, Any]]] = None
        self._broadcast_task: Optional[asyncio.Task] = None
        self._shutdown_requested = False
        self._telemetry_timer = None
        self._last_cpu = 25.0
        self._last_mem = 45.0
        self._last_temp = 40.0

        # 注意：事件订阅在 start() 中进行，避免 __init__ -> start() 之间的事件丢失

    def _subscribe_events(self) -> None:
        """在事件循环就绪后再订阅事件，避免事件丢失"""
        self.message_bus.subscribe(EventType.SYSTEM_STATE_CHANGE, self._on_state_change)
        self.message_bus.subscribe(EventType.DIALOG_STATE_CHANGED, self._on_dialog_state_changed)
        self.message_bus.subscribe(EventType.WAKE_WORD_DETECTED, self._on_wakeword)
        self.message_bus.subscribe(EventType.AUDIO_START_RECORDING, self._on_audio_start)
        self.message_bus.subscribe(EventType.AUDIO_STOP_RECORDING, self._on_audio_stop)
        self.message_bus.subscribe(EventType.AUDIO_OUTPUT, self._on_audio_output)
        self.message_bus.subscribe(EventType.AUDIO_OUTPUT_COMPLETE, self._on_audio_complete)
        self.message_bus.subscribe(EventType.NLP_RESPONSE_DONE, self._on_nlp_response)
        self.message_bus.subscribe(EventType.NLP_RESPONSE_CHUNK, self._on_nlp_response_chunk)
        self.message_bus.subscribe(EventType.NLP_TRANSCRIBE_DONE, self._on_transcribe_done)
        self.message_bus.subscribe(EventType.MUSIC_PLAY, self._on_music_play)
        self.message_bus.subscribe(EventType.MUSIC_PAUSE, self._on_music_pause)
        self.message_bus.subscribe(EventType.MUSIC_STOP, self._on_music_stop)
        self.message_bus.subscribe(EventType.MUSIC_RESUME, self._on_music_resume)
        self.message_bus.subscribe(EventType.MUSIC_NEXT, self._on_music_play)
        self.message_bus.subscribe(EventType.MUSIC_PREV, self._on_music_play)
        self.message_bus.subscribe(EventType.MUSIC_PREVIOUS, self._on_music_play)
        self.message_bus.subscribe(EventType.MUSIC_TOGGLE, self._on_music_toggle)
        self.message_bus.subscribe(EventType.MUSIC_VOLUME, self._on_music_volume)
        self.message_bus.subscribe(EventType.SYSTEM_STATUS, self._on_system_status)
        self.message_bus.subscribe(EventType.VAD_START, self._on_vad_start)
        self.message_bus.subscribe(EventType.VAD_END, self._on_vad_end)

    async def start(self):
        """启动WebSocket服务器"""
        if self.running:
            return

        self.running = True
        self._event_loop = asyncio.get_running_loop()
        self._broadcast_queue = asyncio.Queue(maxsize=100)

        self._subscribe_events()

        self.server = await websockets.serve(
            self.handle_client,
            self.host,
            self.port
        )

        self._broadcast_task = asyncio.create_task(self._process_broadcast_queue())

        self._start_telemetry()

        logger.info(f"WebSocket broadcaster started on ws://{self.host}:{self.port}")

    async def stop(self):
        """停止WebSocket服务器"""
        if not self.running:
            return

        self.running = False

        self._stop_telemetry()

        if self._broadcast_task:
            self._broadcast_task.cancel()
            self._broadcast_task = None

        with self._clients_lock:
            for client in list(self.clients.values()):
                try:
                    await asyncio.wait_for(client.close(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("Client close timeout")
                except Exception:
                    pass

            self.clients.clear()

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        logger.info("WebSocket broadcaster stopped")
    
    def stop_sync(self):
        """线程安全的停止方法，可从其他线程调用"""
        if not self.running:
            return

        if self._event_loop and self._event_loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self.stop(), self._event_loop)
                future.result(timeout=3.0)
                logger.info("WebSocket broadcaster stopped via thread-safe method")
            except Exception as e:
                logger.error(f"Failed to stop WebSocket broadcaster safely: {e}")
        else:
            logger.warning("Event loop not running, cannot stop WebSocket broadcaster")
    
    async def handle_client(self, websocket, path=None):
        """处理客户端连接（兼容新旧版websockets：path参数可选）"""
        # 防御remote_address为None（握手期断开）
        ra = websocket.remote_address or ('?', 0)
        client_id = f"{ra[0]}:{ra[1]}"

        with self._clients_lock:
            self.clients[client_id] = websocket

        logger.info(f"[WS] 客户端连接: {client_id}, 当前客户端数: {len(self.clients)}")

        try:
            # [防阻塞修复] 发送欢迎消息带超时
            welcome_message = {
                "type": "welcome",
                "message": "Connected to Smart Speaker",
                "timestamp": time.time()
            }
            await asyncio.wait_for(
                websocket.send(json.dumps(welcome_message)),
                timeout=2.0
            )

            # 发送歌曲列表
            try:
                from ..audio.player_manager import get_player_manager
                manager = get_player_manager()
                song_list = manager.get_song_list()
                await websocket.send(json.dumps({
                    "type": "song_list",
                    "songs": song_list,
                    "count": len(song_list),
                    "timestamp": time.time()
                }))
            except Exception as e:
                logger.warning(f"Failed to send song list: {e}")
            
            # [防阻塞修复] 发送当前状态带超时
            current_state = SystemState.IDLE.value
            state_message = {
                "type": "state_change",
                "from_state": "unknown",
                "to_state": current_state,
                "trigger": "connection",
                "timestamp": time.time()
            }
            await asyncio.wait_for(
                websocket.send(json.dumps(state_message)),
                timeout=2.0
            )
            
            logger.info(f"Client connected: {client_id}")
            
            async for message in websocket:
                await self.handle_client_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.TimeoutError:
            logger.warning(f"Client {client_id} welcome message timeout")
        except Exception as e:
            logger.error(f"Client {client_id} error: {e}")
        finally:
            # 清理客户端连接
            with self._clients_lock:
                if client_id in self.clients:
                    del self.clients[client_id]
            logger.info(f"Client disconnected: {client_id}")
    
    async def handle_client_message(self, websocket, message):
        """处理客户端消息"""
        try:
            data = json.loads(message)
            message_type = data.get("type")
            action = data.get("action")
            
            if message_type == "ping":
                await asyncio.wait_for(
                    websocket.send(json.dumps({
                        "type": "pong",
                        "timestamp": time.time()
                    })),
                    timeout=1.0
                )
            
            elif message_type == "get_state":
                current_state = SystemState.IDLE.value
                await asyncio.wait_for(
                    websocket.send(json.dumps({
                        "type": "state_info",
                        "state": current_state,
                        "timestamp": time.time()
                    })),
                    timeout=1.0
                )
            
            elif message_type == "interrupt" or action == "stop_audio":
                self.message_bus.publish(Event(EventType.AUDIO_INTERRUPT, {
                    "reason": "websocket_interrupt",
                    "client_id": websocket.remote_address[0]
                }))
                
                await asyncio.wait_for(
                    websocket.send(json.dumps({
                        "type": "interrupt_ack",
                        "message": "Interrupt signal sent",
                        "timestamp": time.time()
                    })),
                    timeout=1.0
                )
            
            elif message_type == "set_mode":
                mode = data.get("mode", 1)
                logger.info(f"[WebSocket] 客户端请求切换模式: {mode}")
                self.message_bus.publish(Event(EventType.SYSTEM_MODE_CHANGE, {
                    "mode": mode,
                    "mode_name": self._get_mode_name(mode)
                }))
                await asyncio.wait_for(
                    websocket.send(json.dumps({
                        "type": "mode_change",
                        "mode": mode,
                        "mode_name": self._get_mode_name(mode),
                        "timestamp": time.time()
                    })),
                    timeout=1.0
                )
            
            elif message_type == "send_text" or action == "text_input":
                text = data.get("text", "")
                if text:
                    logger.info(f"[WebSocket] 客户端发送文字: {text}")
                    self.message_bus.publish(Event(EventType.DIALOG_START, {
                        "trigger": "text_input",
                        "text": text,
                    }))
                    self.message_bus.publish(Event(EventType.NLP_TRANSCRIBE_DONE, {
                        "text": text,
                        "duration": 2.0
                    }))
                    await asyncio.wait_for(
                        websocket.send(json.dumps({
                            "type": "text_received",
                            "text": text,
                            "timestamp": time.time()
                        })),
                        timeout=1.0
                    )

            elif message_type == "music_play":
                song_index = data.get("song_index", 0)
                logger.info(f"[WebSocket] 播放音乐: 索引 {song_index}")
                self.message_bus.publish(Event(EventType.MUSIC_PLAY, {
                    "song_index": song_index
                }))

            elif message_type == "music_pause":
                logger.info("[WebSocket] 暂停音乐")
                self.message_bus.publish(Event(EventType.MUSIC_PAUSE, {}))

            elif message_type == "music_stop":
                logger.info("[WebSocket] 停止音乐")
                self.message_bus.publish(Event(EventType.MUSIC_STOP, {}))

            elif message_type == "music_next":
                logger.info("[WebSocket] 下一首")
                self.message_bus.publish(Event(EventType.MUSIC_NEXT, {}))

            elif message_type == "music_prev":
                logger.info("[WebSocket] 上一首")
                self.message_bus.publish(Event(EventType.MUSIC_PREV, {}))

            elif message_type == "music_toggle":
                logger.info("[WebSocket] 播放/暂停切换")
                # 只发布事件，不立即读状态（避免竞态）；
                # player.toggle() 内部会发布 MUSIC_PAUSE/MUSIC_RESUME/MUSIC_PLAY 事件，
                # 由 _on_music_pause/_on_music_resume/_on_music_play 广播给所有客户端
                self.message_bus.publish(Event(EventType.MUSIC_TOGGLE, {}))
                # 发送确认（前端依赖事件广播更新实际状态）
                await websocket.send(json.dumps({
                    "type": "music_toggle_ack",
                    "timestamp": time.time()
                }))

            elif message_type == "get_music_status":
                try:
                    from ..audio.player_manager import get_player_manager
                    manager = get_player_manager()
                    status = manager.get_status()
                    await websocket.send(json.dumps({
                        "type": "music_status",
                        **status,
                        "timestamp": time.time()
                    }))
                except Exception as e:
                    await websocket.send(json.dumps({"type": "error", "message": str(e)}))

            elif message_type == "music_volume":
                volume = data.get("volume", 50)
                logger.info(f"[WebSocket] 设置音量: {volume}")
                try:
                    from ..audio.player_manager import get_player_manager
                    manager = get_player_manager()
                    player = manager.get_player()
                    player.set_volume(int(volume))
                    await websocket.send(json.dumps({
                        "type": "music_volume_changed",
                        "volume": int(volume),
                        "timestamp": time.time()
                    }))
                except Exception as e:
                    logger.error(f"[WebSocket] 设置音量失败: {e}")

            elif message_type == "get_songs":
                try:
                    from ..audio.player_manager import get_player_manager
                    manager = get_player_manager()
                    song_list = manager.get_song_list()
                    await websocket.send(json.dumps({
                        "type": "song_list",
                        "songs": song_list,
                        "count": len(song_list),
                        "timestamp": time.time()
                    }))
                except Exception as e:
                    await websocket.send(json.dumps({"type": "error", "message": str(e)}))

            elif message_type == "simulate_wake" or action == "wake_up":
                logger.info("[WebSocket] 客户端模拟唤醒词")
                self.message_bus.publish(Event(EventType.WAKE_WORD_DETECTED, {
                    "confidence": 0.95,
                    "timestamp": time.time()
                }))
                await asyncio.wait_for(
                    websocket.send(json.dumps({
                        "type": "wake_simulated",
                        "message": "唤醒词已模拟",
                        "timestamp": time.time()
                    })),
                    timeout=1.0
                )

            elif message_type == "shutdown":
                logger.info("[WebSocket] 收到 shutdown 指令，准备关闭系统")
                self._shutdown_requested = True
                # 通知所有客户端：系统即将关闭
                try:
                    await asyncio.wait_for(
                        websocket.send(json.dumps({
                            "type": "shutdown",
                            "status": "shutting_down",
                            "message": "系统正在关闭",
                            "timestamp": time.time()
                        })),
                        timeout=1.0
                    )
                except Exception:
                    pass
                # 发布系统状态事件，触发整体关闭流程
                self.message_bus.publish(Event(EventType.SYSTEM_STATUS, {
                    "status": "shutdown",
                    "source": "websocket",
                }))
            
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON message from client: {message}")
        except asyncio.TimeoutError:
            logger.warning("Response to client timed out")
        except Exception as e:
            logger.error(f"Error handling client message: {e}")
    
    def _get_mode_name(self, mode):
        mode_names = {
            1: '演示模式',
            2: '文字交互',
            3: '语音交互'
        }
        return mode_names.get(mode, '未知模式')
    
    async def _process_broadcast_queue(self):
        """[防阻塞修复] 异步广播处理循环，从队列中取出消息并发送"""
        while self.running:
            try:
                # [防阻塞修复] 队列读取带超时，防止无限等待
                message = await asyncio.wait_for(
                    self._broadcast_queue.get(),
                    timeout=3.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            
            try:
                await self._broadcast_message_to_clients(message)
            except Exception as e:
                logger.error(f"Broadcast processing error: {e}")
            finally:
                self._broadcast_queue.task_done()
    
    async def _broadcast_message_to_clients(self, message: Dict[str, Any]):
        """[防阻塞修复] 实际广播消息给所有客户端

        锁内只取快照，锁外做异步发送，避免长时间持锁阻塞其它协程。
        """
        # 锁内只复制快照
        with self._clients_lock:
            if not self.clients:
                logger.debug(f"[WS Broadcast] 无客户端连接，跳过广播: {message.get('type')}")
                return
            clients_snapshot = list(self.clients.items())

        message_str = json.dumps(message)
        disconnected_clients = []

        logger.debug(f"[WS Broadcast] 广播消息: {message.get('type')} 给 {len(clients_snapshot)} 个客户端")

        # 锁外异步发送
        for client_id, client in clients_snapshot:
            try:
                await asyncio.wait_for(
                    client.send(message_str),
                    timeout=1.0
                )
            except websockets.exceptions.ConnectionClosed:
                disconnected_clients.append(client_id)
            except asyncio.TimeoutError:
                logger.warning(f"Send to {client_id} timed out")
                disconnected_clients.append(client_id)
            except Exception as e:
                logger.error(f"Error broadcasting to {client_id}: {e}")
                disconnected_clients.append(client_id)

        # 锁内清理断开的客户端
        if disconnected_clients:
            with self._clients_lock:
                for client_id in disconnected_clients:
                    if client_id in self.clients:
                        del self.clients[client_id]
                        logger.info(f"[WS] 客户端断开: {client_id}")
    
    def _schedule_broadcast(self, message: Dict[str, Any]):
        """[防阻塞修复] 在事件循环中调度广播消息，使用队列缓冲"""
        if not self.running:
            return
        if self._event_loop and self._broadcast_queue is not None:
            try:
                self._event_loop.call_soon_threadsafe(self._broadcast_queue.put_nowait, message)
                logger.debug(f"[WS] Scheduled broadcast: {message.get('type')}")
            except Exception as e:
                logger.warning(f"[WS] Schedule broadcast failed: {e}")
        else:
            logger.warning(f"[WS] Cannot schedule broadcast: loop={self._event_loop is not None}, queue={self._broadcast_queue is not None}")
    
    def _start_telemetry(self):
        """启动定时遥测数据采集"""
        if self._telemetry_timer:
            return
        self._telemetry_timer = threading.Timer(2.0, self._send_telemetry_data)
        self._telemetry_timer.daemon = True
        self._telemetry_timer.start()
        logger.info("Telemetry broadcast started")

    def _stop_telemetry(self):
        """停止遥测数据采集"""
        if self._telemetry_timer:
            self._telemetry_timer.cancel()
            self._telemetry_timer = None
        logger.info("Telemetry broadcast stopped")

    def _send_telemetry_data(self):
        """发送遥测数据给所有客户端"""
        if not self.running:
            return
        data = self._collect_telemetry()
        message = {
            "type": "telemetry",
            "data": data,
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)

        # 同时广播音乐进度（使用线程安全的 get_progress 方法）
        try:
            from ..audio.player_manager import get_player_manager
            manager = get_player_manager()
            player = manager.get_player()
            # 优先使用 get_progress 线程安全方法；不支持时回退
            if hasattr(player, 'get_progress'):
                progress = player.get_progress()
                if progress.get("is_playing") or progress.get("is_paused"):
                    progress_msg = {
                        "type": "music_progress",
                        "position": progress["position"],
                        "duration": progress["duration"],
                        "is_playing": progress["is_playing"],
                        "is_paused": progress["is_paused"],
                        "timestamp": time.time()
                    }
                    self._schedule_broadcast(progress_msg)
        except Exception as e:
            logger.debug(f"[WS] 音乐进度广播失败: {e}")

        # 竞态修复：再次检查 running，避免 stop 后重新创建定时器
        if not self.running:
            return
        self._telemetry_timer = threading.Timer(2.0, self._send_telemetry_data)
        self._telemetry_timer.daemon = True
        self._telemetry_timer.start()

    def _collect_telemetry(self):
        """采集系统遥测数据"""
        data = {}
        try:
            import psutil
            data["cpu"] = round(psutil.cpu_percent(interval=0.1), 1)
            mem = psutil.virtual_memory()
            data["memory"] = round(mem.percent, 1)
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        data["temperature"] = round(entries[0].current, 1)
                        break
            else:
                data["temperature"] = self._last_temp
        except ImportError:
            import random
            data["cpu"] = round(max(5, min(95, self._last_cpu + (random.random() - 0.5) * 8)), 1)
            data["memory"] = round(max(10, min(90, self._last_mem + (random.random() - 0.5) * 4)), 1)
            data["temperature"] = round(max(30, min(80, self._last_temp + (random.random() - 0.5) * 3)), 1)
            self._last_cpu = data["cpu"]
            self._last_mem = data["memory"]
            self._last_temp = data["temperature"]
        except Exception as e:
            data["cpu"] = self._last_cpu
            data["memory"] = self._last_mem
            data["temperature"] = self._last_temp
        data["wifi_rssi"] = self._get_wifi_rssi()
        return data

    def _get_wifi_rssi(self):
        """获取WiFi信号强度"""
        try:
            import subprocess
            if platform.system() == "Linux":
                result = subprocess.run(
                    ["iwconfig", "wlan0"],
                    capture_output=True, text=True
                )
                for line in result.stdout.split("\n"):
                    if "Signal level" in line:
                        parts = line.split("=")
                        for part in parts:
                            if "dBm" in part:
                                return int(part.strip().replace(" dBm", ""))
            return -50
        except Exception:
            return -50

    def _on_state_change(self, event: Event):
        """处理状态变化"""
        data = event.data
        message = {
            "type": "state_change",
            "from_state": data.get("from_state"),
            "to_state": data.get("to_state"),
            "trigger": data.get("trigger"),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_dialog_state_changed(self, event: Event):
        """处理对话状态变化"""
        data = event.data
        state = data.get("state", "idle")
        # 将 responding 映射为 speaking，前端只识别 speaking
        if state == "responding":
            state = "speaking"
        message = {
            "type": "state_change",
            "from_state": "unknown",
            "to_state": state,
            "trigger": "dialog",
            "timestamp": time.time()
        }
        logger.info(f"[WS Broadcast] 状态变化: {state}, 客户端数: {len(self.clients)}")
        self._schedule_broadcast(message)
    
    def _on_vad_start(self, event: Event):
        """处理VAD开始"""
        message = {
            "type": "audio_start",
            "mode": "vad",
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_vad_end(self, event: Event):
        """处理VAD结束"""
        message = {
            "type": "audio_stop",
            "duration": event.data.get("duration", 0),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_wakeword(self, event: Event):
        """处理唤醒词检测"""
        message = {
            "type": "wakeword_detected",
            "confidence": event.data.get("confidence", 0),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_audio_start(self, event: Event):
        """处理音频开始"""
        message = {
            "type": "audio_start",
            "mode": event.data.get("mode", "unknown"),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_audio_stop(self, event: Event):
        """处理音频停止"""
        message = {
            "type": "audio_stop",
            "duration": event.data.get("duration", 0),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_audio_output(self, event: Event):
        """处理音频输出"""
        message = {
            "type": "audio_output",
            "text": event.data.get("text", ""),
            "engine": event.data.get("engine", "unknown"),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_audio_complete(self, event: Event):
        """处理音频完成"""
        message = {
            "type": "audio_complete",
            "duration": event.data.get("duration", 0),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_nlp_response(self, event: Event):
        """处理NLP响应完成"""
        message = {
            "type": "nlp_response_done",
            "text": event.data.get("text", ""),
            "intent": event.data.get("intent", "unknown"),
            "confidence": event.data.get("confidence", 0),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_nlp_response_chunk(self, event: Event):
        """处理NLP流式响应片段"""
        message = {
            "type": "nlp_response_chunk",
            "text": event.data.get("text", ""),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)

    def _on_system_status(self, event: Event):
        """处理系统状态事件（含大模型加载状态），推送给前端UI"""
        status = event.data.get("status", "")
        message_text = event.data.get("message", "")
        category = event.data.get("category", "")
        if category != "model" and not str(status).startswith("llm_"):
            return
        message = {
            "type": "model_status",
            "status": status,
            "message": message_text,
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_transcribe_done(self, event: Event):
        """处理语音转写完成"""
        message = {
            "type": "transcript_updated",
            "text": event.data.get("text", ""),
            "duration": event.data.get("duration", 0),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_music_play(self, event: Event):
        """处理音乐播放"""
        song = event.data.get("song", {})
        # 获取当前歌曲索引
        song_index = -1
        try:
            from ..audio.player_manager import get_player_manager
            manager = get_player_manager()
            player = manager.get_player()
            song_index = getattr(player, '_current_song_index', -1)
            # 如果 event 没带 song，尝试从 player 获取
            if not song:
                current = player.current_song
                if current:
                    song = current
        except Exception as e:
            logger.debug(f"获取歌曲索引失败: {e}")
        message = {
            "type": "music_play",
            "status": "playing",
            "song_name": song.get("title", ""),
            "artist": song.get("artist", ""),
            "song_index": song_index,
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_music_pause(self, event: Event):
        """处理音乐暂停"""
        song = event.data.get("current_song", {})
        try:
            from ..audio.player_manager import get_player_manager
            manager = get_player_manager()
            player = manager.get_player()
            current = player.current_song
            if current:
                song = current
        except Exception as e:
            logger.debug(f"获取当前歌曲失败: {e}")
        message = {
            "type": "music_pause",
            "status": "paused",
            "song_name": song.get("title", ""),
            "artist": song.get("artist", ""),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)

    def _on_music_toggle(self, event: Event):
        """处理音乐播放/暂停切换事件

        注意：player.toggle() 内部会发布 MUSIC_PAUSE/MUSIC_RESUME/MUSIC_PLAY 事件，
        由对应的 _on_music_pause/_on_music_resume/_on_music_play 负责广播真实状态。
        此处不直接读取 player 状态，避免与 toggle() 执行产生竞态（旧状态读取）。
        """
        # 不广播状态，只记录日志；真实状态由 pause/resume/play 事件广播
        logger.debug("[WS] 收到 MUSIC_TOGGLE 事件，等待真实状态广播")

    def _on_music_volume(self, event: Event):
        """处理音乐音量变化，广播给所有客户端"""
        volume = event.data.get("volume", 50)
        message = {
            "type": "music_volume_changed",
            "volume": volume,
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)

    def _on_music_resume(self, event: Event):
        """处理音乐继续播放"""
        song = event.data.get("current_song", {})
        message = {
            "type": "music_resume",
            "status": "playing",
            "song_name": song.get("title", ""),
            "artist": song.get("artist", ""),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)
    
    def _on_music_stop(self, event: Event):
        """处理音乐停止"""
        song = event.data.get("current_song", {})
        message = {
            "type": "music_stop",
            "status": "stopped",
            "song_name": song.get("title", ""),
            "artist": song.get("artist", ""),
            "timestamp": time.time()
        }
        self._schedule_broadcast(message)