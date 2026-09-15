from __future__ import annotations
from typing import Any, Dict, Optional
import random
import re
import time

from .base import BaseSkill, SkillResult
from ..utils.logger import logger


class WeatherSkill(BaseSkill):
    def __init__(self) -> None:
        super().__init__("weather", "查询天气、温度、空气质量等信息")
        self._cities = ["北京", "上海", "广州", "深圳", "杭州", "成都"]
        self._weather_types = ["晴", "多云", "阴", "小雨", "中雨", "雷阵雨"]

    def can_handle(self, intent: str, entities: Dict[str, Any]) -> bool:
        return intent == "weather"

    def execute(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        city = entities.get("city", "本地")
        date = entities.get("date", "今天")

        temperature = random.randint(18, 35)
        weather = random.choice(self._weather_types)
        humidity = random.randint(30, 80)
        air_quality = random.choice(["优", "良", "轻度污染"])
        wind = random.choice(["东风", "南风", "西风", "北风", "微风"])

        text = f"{date}{city}天气{weather}，气温{temperature}度，湿度{humidity}%，{wind}，空气质量{air_quality}。"

        return SkillResult(
            success=True,
            data={
                "city": city,
                "date": date,
                "temperature": temperature,
                "weather": weather,
                "humidity": humidity,
                "air_quality": air_quality,
                "wind": wind,
            },
            message="天气查询成功",
            speak_text=text,
        )


class MusicSkill(BaseSkill):
    def __init__(self, music_player: Optional[Any] = None) -> None:
        super().__init__("music", "播放音乐、控制播放状态")
        self._is_playing = False
        self._current_song = ""
        self._volume = 50
        self._playlist = [
            "夜曲 - 周杰伦",
            "稻香 - 周杰伦",
            "晴天 - 周杰伦",
            "七里香 - 周杰伦",
            "青花瓷 - 周杰伦",
            "演员 - 薛之谦",
            "刚好遇见你 - 李玉刚",
        ]
        # 优先使用注入的全局 MusicPlayer 实例，避免出现多个独立实例
        if music_player is not None:
            self._player = music_player
        else:
            from ..audio.music_player import MusicPlayer
            self._player = MusicPlayer()
        self._last_action_time = 0  # 操作防抖时间戳
        self._action_cooldown = 2.0  # 操作冷却时间（秒）

    def can_handle(self, intent: str, entities: Dict[str, Any]) -> bool:
        return intent == "music"

    def execute(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        text = entities.get("text", "").lower()
        speak = ""

        # 防抖检查：短时间内多次操作忽略
        now = time.time()
        if now - self._last_action_time < self._action_cooldown:
            logger.debug(f"[Music] 操作冷却中，忽略请求: {text}")
            # 修复：冷却时给用户明确反馈，不要静默
            return SkillResult(success=True, message="操作冷却中", speak_text="操作太快了，请稍等一下。")
        self._last_action_time = now

        if "暂停" in text or "停止" in text:
            self._player.pause()
            speak = "好的，已暂停播放。"
        elif "继续" in text:
            if self._player.is_paused:
                self._player.resume()
                current = self._player.current_song
                if current:
                    artist = current.get('artist', '')
                    title = current.get('title', '')
                    if artist:
                        speak = f"好的，继续播放{artist}的{title}。"
                    else:
                        speak = f"好的，继续播放{title}。"
                else:
                    speak = "好的，继续播放。"
            else:
                speak = "当前没有暂停的歌曲。"
        elif "下一首" in text or "切歌" in text:
            if self._player.library_count == 0:
                # 修复：库为空时不要假装播放，诚实告知
                speak = "音乐库为空，无法切歌，请先添加音乐文件。"
            else:
                next_song = self._player.next()
                if next_song:
                    speak = f"好的，正在为您播放{next_song.get('artist', '')}的{next_song.get('title', '')}。"
                else:
                    speak = "切歌失败，请重试。"
        elif "上一首" in text:
            if self._player.library_count == 0:
                speak = "音乐库为空，无法切歌，请先添加音乐文件。"
            else:
                prev_song = self._player.previous()
                if prev_song:
                    speak = f"好的，正在为您播放{prev_song.get('artist', '')}的{prev_song.get('title', '')}。"
                else:
                    speak = "上一首失败，请重试。"
        elif "音量" in text:
            import re
            num_match = re.search(r"(\d+)", text)
            if num_match:
                vol = int(num_match.group(1))
                self._player.set_volume(vol)
                speak = f"好的，音量已设置为{vol}%。"
            elif "大" in text or "高" in text:
                new_vol = min(100, self._player.volume + 10)
                self._player.set_volume(new_vol)
                speak = f"好的，音量已调大到{new_vol}%。"
            elif "小" in text or "低" in text:
                new_vol = max(0, self._player.volume - 10)
                self._player.set_volume(new_vol)
                speak = f"好的，音量已调小到{new_vol}%。"
            else:
                speak = f"当前音量为{self._player.volume}%。"
        else:
            # 播放音乐逻辑
            import re
            # 1. 先检查是否是"播放第N首"格式
            nth_match = re.search(r"第\s*(\d+)\s*首", text)
            if nth_match:
                idx = int(nth_match.group(1)) - 1
                if 0 <= idx < self._player.library_count:
                    song = self._player._library.get_song_by_index(idx)
                    if song:
                        self._player.play(song)
                        self._is_playing = True
                        artist = song.get('artist', '')
                        title = song.get('title', '')
                        speak = f"好的，正在为您播放{artist}的{title}。" if artist else f"好的，正在为您播放{title}。"
                    else:
                        speak = "抱歉，无法播放这首歌。"
                else:
                    speak = f"抱歉，库中只有{self._player.library_count}首歌曲。"
            else:
                # 2. 搜索歌曲
                search_results = []
                clean_text = text
                for cmd_word in ["播放", "放", "来", "首", "歌", "音乐", "听", "一下"]:
                    clean_text = clean_text.replace(cmd_word, "")
                clean_text = clean_text.strip()

                if clean_text:
                    search_results = self._player.search(clean_text)
                if not search_results and text:
                    search_results = self._player.search(text)

                if search_results:
                    song = search_results[0]
                    self._player.play(song)
                    self._is_playing = True
                    artist = song.get('artist', '')
                    title = song.get('title', '')
                    speak = f"好的，正在为您播放{artist}的{title}。" if artist else f"好的，正在为您播放{title}。"
                elif self._player.library_count > 0:
                    import random
                    idx = random.randint(0, self._player.library_count - 1)
                    song = self._player._library.get_song_by_index(idx)
                    if song:
                        self._player.play(song)
                        self._is_playing = True
                        artist = song.get('artist', '')
                        title = song.get('title', '')
                        speak = f"好的，正在为您播放{artist}的{title}。" if artist else f"好的，正在为您播放{title}。"
                    else:
                        speak = "抱歉，音乐库中暂时没有可播放的歌曲。"
                else:
                    speak = "抱歉，音乐库中暂时没有歌曲，请先添加音乐文件到data/music目录。"

        return SkillResult(
            success=True,
            data={
                "is_playing": self._is_playing,
                "current_song": self._player.current_song or {"artist": "", "title": self._current_song},
                "volume": self._player.volume,
                "library_count": self._player.library_count,
                "song_path": self._player.current_song.get("path") if self._player.current_song else None,
            },
            message="音乐控制成功",
            speak_text=speak,
        )


class AlarmSkill(BaseSkill):
    def __init__(self) -> None:
        super().__init__("alarm", "设置闹钟、提醒、查询时间")
        self._alarms = []

    def can_handle(self, intent: str, entities: Dict[str, Any]) -> bool:
        return intent == "alarm"

    def execute(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        text = entities.get("text", "")

        if "几点" in text or "时间" in text:
            from datetime import datetime
            now = datetime.now()
            time_str = now.strftime("%H点%M分")
            date_str = now.strftime("%Y年%m月%d日 %A")
            speak = f"现在是{time_str}，{date_str}。"
            return SkillResult(
                success=True,
                data={"current_time": now.isoformat()},
                message="时间查询成功",
                speak_text=speak,
            )

        if "闹钟" in text or "提醒" in text:
            import re
            time_match = re.search(r"(\d{1,2})\s*点\s*(\d{0,2})", text)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2) or 0)
                self._alarms.append({"hour": hour, "minute": minute, "enabled": True})
                speak = f"好的，已为您设置{hour}点{minute}分的闹钟。"
            else:
                speak = "好的，已为您设置闹钟。"
            return SkillResult(
                success=True,
                data={"alarms_count": len(self._alarms)},
                message="闹钟设置成功",
                speak_text=speak,
            )

        return SkillResult(
            success=False,
            message="未知指令",
            speak_text="抱歉，我不太明白您的意思。",
        )


class JokeSkill(BaseSkill):
    def __init__(self) -> None:
        super().__init__("joke", "讲笑话、娱乐互动")
        self._jokes = [
            "为什么程序员总是分不清万圣节和圣诞节？因为 Oct 31 = Dec 25。",
            "有一天0碰到8，0说：胖就胖呗，还系腰带。",
            "为什么鱼不会弹钢琴？因为它们怕掉秤（音阶）。",
            "我问风扇我丑不丑，它摇了一晚上的头。",
            "以前觉得靠关系的人没本事，现在觉得靠关系的人真有本事。",
            "我女朋友让我形容她，我说你是我的优乐美，这样我就可以把你捧在手心。她说：不，我是你的优乐美，因为你喝完就想扔。",
        ]
        self._index = 0

    def can_handle(self, intent: str, entities: Dict[str, Any]) -> bool:
        return intent == "joke"

    def execute(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        joke = self._jokes[self._index % len(self._jokes)]
        self._index += 1
        return SkillResult(
            success=True,
            data={"joke": joke},
            message="笑话播放成功",
            speak_text=joke,
        )


class ChatSkill(BaseSkill):
    def __init__(self) -> None:
        super().__init__("chat", "闲聊、打招呼、自我介绍")

    def can_handle(self, intent: str, entities: Dict[str, Any]) -> bool:
        return intent == "chat"

    def execute(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        text = entities.get("text", "")

        if "你是谁" in text or "你叫什么" in text:
            speak = "我是智能音箱小智，是您的智能生活助手。我可以帮您查询天气、播放音乐、控制智能家居，还可以陪您聊天解闷。"
        elif "你好" in text or "在吗" in text:
            speak = "你好呀！我在呢，有什么可以帮您的吗？"
        else:
            speak = "你好！我是小智，很高兴为您服务。"

        return SkillResult(
            success=True,
            data={},
            message="闲聊成功",
            speak_text=speak,
        )


class SmartHomeSkill(BaseSkill):
    def __init__(self) -> None:
        super().__init__("smarthome", "控制智能家居设备，支持Matter协议")
        self._devices = {}
        self._matter_client = None
        self._initialized = False

    def _init_matter(self) -> bool:
        # 关键修复：无论matter是否可用，都只初始化一次，避免每次execute重置设备状态
        if self._initialized:
            return True

        mock_devices = {
            "客厅灯": {"id": 1, "type": "light", "state": {"on": False, "brightness": 50}},
            "卧室灯": {"id": 2, "type": "light", "state": {"on": False, "brightness": 80}},
            "台灯": {"id": 5, "type": "light", "state": {"on": False, "brightness": 60}},
            "空调": {"id": 3, "type": "thermostat", "state": {"on": False, "temperature": 25}},
            "窗帘": {"id": 4, "type": "cover", "state": {"open": False}},
        }

        try:
            from matter_server.client import MatterClient
            import asyncio

            self._matter_client = MatterClient("ws://localhost:5580/ws")

            async def connect():
                await self._matter_client.connect()

            loop = asyncio.new_event_loop()
            loop.run_until_complete(connect())

            async def get_devices():
                devices = await self._matter_client.get_devices()
                for dev in devices:
                    self._devices[dev.name] = {
                        "id": dev.device_id,
                        "type": dev.device_type,
                        "state": {},
                    }

            loop.run_until_complete(get_devices())
            loop.close()

            self._initialized = True
            logger.info(f"Matter client connected, {len(self._devices)} devices found")
            return True
        except ImportError:
            logger.warning("python-matter-server not installed, using mock mode")
        except Exception as e:
            logger.error(f"Failed to initialize Matter client: {e}")

        # 失败也标记为已初始化，使用mock设备，避免每次execute都重置
        self._devices = mock_devices
        self._initialized = True
        return False

    def can_handle(self, intent: str, entities: Dict[str, Any]) -> bool:
        return intent == "smarthome" or any(keyword in entities.get("text", "").lower() for keyword in ["灯", "空调", "窗帘", "智能家居", "设备"])

    def execute(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        self._init_matter()

        text = entities.get("text", "").lower()
        device_name = self._extract_device_name(text)
        action = self._extract_action(text)

        if not device_name or device_name not in self._devices:
            device_list = ", ".join(self._devices.keys())
            return SkillResult(
                success=False,
                data={"available_devices": list(self._devices.keys())},
                message=f"未找到设备，可用设备：{device_list}",
                speak_text=f"抱歉，我没找到这个设备。可用的设备有：{device_list}。",
            )

        device = self._devices[device_name]

        result = self._control_device(device_name, device, action, text)

        return SkillResult(
            success=True,
            data={"device": device_name, "action": action, "state": device["state"]},
            message=f"{device_name} {action}成功",
            speak_text=result,
        )

    def _extract_device_name(self, text: str) -> Optional[str]:
        # 关键字到 _devices 中设备名的映射，避免所有"灯"都被误映射到台灯
        keyword_mapping = {
            "客厅灯": "客厅灯",
            "客厅的灯": "客厅灯",
            "卧室灯": "卧室灯",
            "卧室的灯": "卧室灯",
            "台灯": "台灯",
            "空调": "空调",
            "窗帘": "窗帘",
        }
        for keyword, device_name in keyword_mapping.items():
            if keyword in text:
                return device_name
        # 模糊匹配单字 - 泛指"灯"时默认台灯
        for single in ["灯", "空调", "窗帘", "电视", "风扇"]:
            if single in text:
                if single == "灯":
                    return "台灯"
                return single
        return None

    def _extract_action(self, text: str) -> str:
        # 先处理"窗帘"相关的open/close，避免被通用"打开"覆盖
        if "窗帘" in text:
            if "打开" in text or "拉开" in text:
                return "open"
            if "关闭" in text or "拉上" in text or "关上" in text:
                return "close"
        # 温度调节优先（避免被"打开空调"覆盖到on）
        if "温度" in text or re.search(r"\d+度", text):
            return "temperature"
        if "打开" in text or "开" in text:
            return "on"
        if "关闭" in text or "关" in text:
            return "off"
        if "调亮" in text or "亮一点" in text:
            return "brightness_up"
        if "调暗" in text or "暗一点" in text:
            return "brightness_down"
        return "on"

    def _control_device(self, device_name: str, device: Dict[str, Any], action: str, text: str = "") -> str:
        device_type = device["type"]

        if device_type == "light":
            if action == "on":
                device["state"]["on"] = True
                return f"好的，已为您打开{device_name}。"
            elif action == "off":
                device["state"]["on"] = False
                return f"好的，已为您关闭{device_name}。"
            elif action == "brightness_up":
                device["state"]["brightness"] = min(100, device["state"]["brightness"] + 20)
                return f"好的，{device_name}亮度已调至{device['state']['brightness']}%。"
            elif action == "brightness_down":
                device["state"]["brightness"] = max(0, device["state"]["brightness"] - 20)
                return f"好的，{device_name}亮度已调至{device['state']['brightness']}%。"

        elif device_type == "thermostat":
            if action == "on":
                device["state"]["on"] = True
                return f"好的，已为您打开{device_name}。"
            elif action == "off":
                device["state"]["on"] = False
                return f"好的，已为您关闭{device_name}。"
            elif action == "temperature":
                # 修复：从传入的 text 中解析温度，而非未定义的 entities
                match = re.search(r"(\d{1,2})度", text)
                if match:
                    device["state"]["temperature"] = int(match.group(1))
                else:
                    device["state"]["temperature"] += 1
                return f"好的，{device_name}温度已调至{device['state']['temperature']}度。"
        
        elif device_type == "cover":
            if action == "open" or action == "on":
                device["state"]["open"] = True
                return f"好的，已为您打开{device_name}。"
            elif action == "close" or action == "off":
                device["state"]["open"] = False
                return f"好的，已为您关闭{device_name}。"
        
        return f"好的，已为您{action}{device_name}。"

    def cleanup(self) -> None:
        if self._matter_client:
            import asyncio
            
            async def disconnect():
                await self._matter_client.disconnect()
            
            loop = asyncio.new_event_loop()
            loop.run_until_complete(disconnect())
            loop.close()
            
            logger.info("Matter client disconnected")
