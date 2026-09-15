from __future__ import annotations
import os
import re
import shutil
import signal
import platform
import subprocess
import threading
import time
from typing import List, Dict, Optional
from ..utils import logger, get_project_root


class MusicLibrary:
    SUPPORTED_EXTENSIONS = ['.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma']

    def __init__(self, music_dir: str = None):
        if music_dir is None:
            music_dir = os.path.join(get_project_root(), "data", "music")
        self._music_dir = music_dir
        self._songs: List[Dict] = []
        self._last_scan_time = 0
        self._scan_interval = 10
        self._scan_library()

    def _scan_library(self):
        self._songs = []
        if not os.path.exists(self._music_dir):
            os.makedirs(self._music_dir, exist_ok=True)
            logger.info(f"音乐目录不存在，已创建: {self._music_dir}")
            return

        for root, dirs, files in os.walk(self._music_dir):
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in self.SUPPORTED_EXTENSIONS:
                    song_info = self._parse_filename(filename)
                    song_info['path'] = os.path.join(root, filename)
                    song_info['size'] = os.path.getsize(song_info['path'])
                    self._songs.append(song_info)

        self._last_scan_time = time.time()
        logger.info(f"音乐库扫描完成，共找到 {len(self._songs)} 首歌曲")

    def refresh_if_needed(self):
        now = time.time()
        if now - self._last_scan_time < self._scan_interval:
            return

        current_count = 0
        if os.path.exists(self._music_dir):
            for root, dirs, files in os.walk(self._music_dir):
                for f in files:
                    if os.path.splitext(f)[1].lower() in self.SUPPORTED_EXTENSIONS:
                        current_count += 1

        if current_count != len(self._songs):
            old_count = len(self._songs)
            self._scan_library()
            if len(self._songs) > old_count:
                logger.info(f"音乐库已更新：新增 {len(self._songs) - old_count} 首歌曲")

    def _parse_filename(self, filename: str) -> Dict:
        name, ext = os.path.splitext(filename)
        artist = ""
        title = name

        patterns = [
            r"(.+?)[\s_-]+[-–—]+[\s_-]+(.+)",
            r"(.+?)[\s_-]+[–—]+[\s_-]+(.+)",
            r"(.+?)[\s_-]+-[\s_-]+(.+)",
        ]

        for pattern in patterns:
            match = re.match(pattern, name)
            if match:
                artist = match.group(1).strip().replace('_', ' ')
                title = match.group(2).strip().replace('_', ' ')
                break

        return {
            'filename': filename,
            'artist': artist,
            'title': title,
            'extension': ext,
        }

    def search(self, keyword: str) -> List[Dict]:
        self.refresh_if_needed()
        keyword = keyword.lower().strip()
        if not keyword:
            return self._songs

        keyword_nospace = keyword.replace(" ", "")
        exact_matches = []
        title_matches = []
        artist_matches = []
        filename_matches = []
        nospace_matches = []

        for song in self._songs:
            title_lower = song['title'].lower()
            artist_lower = song['artist'].lower()
            filename_lower = song['filename'].lower()
            title_nospace = title_lower.replace(" ", "")
            artist_nospace = artist_lower.replace(" ", "")
            filename_nospace = filename_lower.replace(" ", "")

            if keyword == title_lower or keyword == artist_lower:
                exact_matches.append(song)
            elif keyword in title_lower:
                title_matches.append(song)
            elif keyword in artist_lower:
                artist_matches.append(song)
            elif keyword in filename_lower:
                filename_matches.append(song)
            elif keyword_nospace in title_nospace or keyword_nospace in artist_nospace or keyword_nospace in filename_nospace:
                nospace_matches.append(song)

        results = exact_matches + title_matches + artist_matches + filename_matches + nospace_matches
        if results:
            logger.debug(f"Music search '{keyword}': found {len(results)} results")
        return results

    def get_song_by_index(self, index: int) -> Optional[Dict]:
        if 0 <= index < len(self._songs):
            return self._songs[index]
        return None

    def list_all(self) -> List[Dict]:
        self.refresh_if_needed()
        return self._songs

    @property
    def songs(self) -> List[Dict]:
        return self._songs

    @property
    def count(self) -> int:
        return len(self._songs)


_music_player_instance = None
_music_player_lock = threading.Lock()


class MusicPlayer:
    def __new__(cls, output_device: Optional[int] = None, bus=None, music_dir: str = None):
        global _music_player_instance
        with _music_player_lock:
            if _music_player_instance is None:
                _music_player_instance = super().__new__(cls)
                _music_player_instance._initialized = False
            return _music_player_instance

    def __init__(self, output_device: Optional[int] = None, bus=None, music_dir: str = None):
        if self._initialized:
            if bus is not None:
                self._bus = bus
            if music_dir is not None:
                self._library = MusicLibrary(music_dir=music_dir)
            return

        self._library = MusicLibrary(music_dir=music_dir)
        self._output_device = output_device
        self._bus = bus
        self._current_song_index = -1
        self._is_playing = False
        self._is_paused = False
        self._volume = 80
        self._playback_process: Optional[subprocess.Popen] = None
        self._control_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._state_lock = threading.RLock()
        self._current_duration = 0
        self._current_position = 0
        self._play_start_time = 0.0
        self._total_pause_time = 0.0
        self._pause_start_time = 0.0
        self._progress_thread: Optional[threading.Thread] = None
        self._progress_stop_event = threading.Event()
        self._player_cmd: Optional[str] = None
        # 世代标记：每次启动新的播放会递增，控制线程检查世代来判断自己是否过期
        self._playback_generation = 0
        # 暂停时记录的播放位置，用于非Linux平台resume时恢复进度
        self._paused_position = 0.0
        self._player_supports_volume: bool = False
        # mpv IPC socket 路径，用于运行时音量调节（无需中断播放）
        self._mpv_ipc_socket: Optional[str] = None
        self._detect_player()
        self._initialized = True
        logger.info("MusicPlayer initialized")

    def _detect_player(self) -> None:
        system = platform.system()
        player_priority = []

        if system == "Linux":
            player_priority = [
                ("ffplay", True),
                ("mpv", True),
                ("mpg123", True),
                ("aplay", False),
                ("cvlc", True),
                ("play", False),
            ]
        elif system == "Darwin":
            player_priority = [
                ("ffplay", True),
                ("mpv", True),
                ("afplay", False),
            ]
        elif system == "Windows":
            player_priority = [
                ("ffplay.exe", True),
                ("mpv.exe", True),
                ("mpg123.exe", True),
                ("ffplay", True),
                ("mpv", True),
            ]
        else:
            player_priority = [
                ("ffplay", True),
                ("mpv", True),
                ("mpg123", True),
            ]

        logger.info(f"[MusicPlayer] 开始探测音乐播放器，系统: {system}")
        logger.info(f"[MusicPlayer] 探测优先级: {[p[0] for p in player_priority]}")

        for cmd, supports_volume in player_priority:
            exe_path = shutil.which(cmd)
            if exe_path is not None:
                self._player_cmd = exe_path
                self._player_supports_volume = supports_volume
                logger.info(f"[MusicPlayer] 找到播放器: {cmd} -> {exe_path}")
                return

        logger.warning(f"[MusicPlayer] shutil.which() 未找到任何播放器，尝试直接执行探测...")

        for cmd, supports_volume in player_priority:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    timeout=2
                )
                if result.returncode == 0:
                    self._player_cmd = cmd
                    self._player_supports_volume = supports_volume
                    logger.info(f"[MusicPlayer] 通过执行探测找到播放器: {cmd}")
                    return
            except Exception as e:
                logger.debug(f"[MusicPlayer] 执行探测 {cmd} 失败: {e}")
                continue

        if system == "Linux":
            common_paths = [
                "/usr/bin/ffplay",
                "/usr/bin/mpv",
                "/usr/bin/mpg123",
                "/usr/bin/aplay",
                "/usr/bin/vlc",
                "/usr/local/bin/ffplay",
                "/usr/local/bin/mpv",
                "/usr/local/bin/mpg123",
            ]
            logger.warning(f"[MusicPlayer] 尝试常见路径探测...")
            for path in common_paths:
                if os.path.exists(path) and os.access(path, os.X_OK):
                    self._player_cmd = path
                    self._player_supports_volume = True
                    logger.info(f"[MusicPlayer] 通过路径探测找到播放器: {path}")
                    return

        logger.error("[ERROR] 未找到可用的音乐播放器，请安装 ffmpeg (ffplay) 或 mpv")

    def _find_player_command(self) -> Optional[str]:
        if self._player_cmd is not None:
            return self._player_cmd

        self._detect_player()
        return self._player_cmd

    def _kill_process(self, process: subprocess.Popen):
        if process.poll() is None:
            # 如果进程被 SIGSTOP 暂停，先 SIGCONT 唤醒再终止，避免僵尸进程
            if platform.system() == "Linux":
                try:
                    os.kill(process.pid, signal.SIGCONT)
                except Exception:
                    pass
            try:
                process.terminate()
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=1)
                except Exception:
                    pass
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def _playback_control_loop(self, generation: int):
        """播放控制线程：监控进程退出，自动播放下一首

        通过 generation 标记防止旧线程误触发：
        每次 _play_song 会递增 generation 并启动新线程，
        旧线程检测到 generation 不匹配会立即退出。
        """
        logger.info(f"Music control loop started (generation={generation})")
        while not self._stop_event.is_set():
            # 检查世代，若已过期则退出
            with self._state_lock:
                if generation != self._playback_generation:
                    logger.info(f"Control loop gen={generation} outdated, exiting")
                    return
                proc = self._playback_process
                is_paused = self._is_paused

            if proc is not None and proc.poll() is not None:
                # 进程退出，再次确认世代
                logger.info(f"[音乐] 检测到播放进程退出 (gen={generation}), paused={is_paused}")
                with self._state_lock:
                    if generation != self._playback_generation:
                        return
                    self._is_playing = False
                    self._is_paused = False
                    self._playback_process = None
                # 仅在非暂停、非主动停止的情况下自动播放下一首
                # （暂停时进程被kill也会触发poll，不应自动下一首）
                if not self._stop_event.is_set() and not is_paused:
                    logger.info(f"[音乐] 自动播放下一首 (gen={generation})")
                    # 在新线程中调用 next，避免在控制线程中执行复杂的重启逻辑
                    threading.Thread(target=self.next, daemon=True, name="MusicAutoNext").start()
                else:
                    logger.info(f"[音乐] 不自动播放下一首: stop_event={self._stop_event.is_set()}, paused={is_paused}")
                return
            time.sleep(0.3)
        logger.info(f"Music control loop stopped (generation={generation})")

    def _get_song_duration(self, filepath: str) -> float:
        """使用 ffprobe 获取歌曲时长（秒），失败返回0"""
        try:
            ffprobe_cmd = "ffprobe" if platform.system() != "Windows" else "ffprobe.exe"
            exe_path = shutil.which(ffprobe_cmd) or ffprobe_cmd
            result = subprocess.run(
                [exe_path, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", filepath],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception as e:
            logger.debug(f"[音乐] 获取时长失败: {e}")
        return 0.0

    def _progress_tracking_loop(self):
        """进度跟踪线程：基于真实时间计算当前播放位置"""
        logger.info("Music progress tracking loop started")
        while not self._progress_stop_event.is_set():
            with self._state_lock:
                if self._is_playing and not self._is_paused and self._play_start_time > 0:
                    elapsed = time.time() - self._play_start_time - self._total_pause_time
                    if self._current_duration > 0:
                        self._current_position = min(elapsed, self._current_duration)
                    else:
                        self._current_position = max(0, elapsed)
            time.sleep(0.5)
        logger.info("Music progress tracking loop stopped")

    def _stop_progress_thread(self):
        """停止进度跟踪线程"""
        self._progress_stop_event.set()
        if self._progress_thread and self._progress_thread.is_alive():
            self._progress_thread.join(timeout=2)
        self._progress_thread = None

    def _stop_control_thread(self):
        """停止旧的控制线程（通过世代标记使其自然退出，并join）"""
        # 递增世代使旧线程自然退出
        with self._state_lock:
            self._playback_generation += 1
        if self._control_thread and self._control_thread.is_alive():
            # 不能join当前线程自身
            if self._control_thread is not threading.current_thread():
                self._control_thread.join(timeout=2)
        self._control_thread = None

    def _play_song(self, song: Dict, start_position: float = 0.0):
        """播放指定歌曲，可从 start_position 秒处开始（用于非Linux恢复进度）

        统一的播放启动逻辑，正确清理旧线程和进程。
        """
        # 0. 确保 _stop_event 处于清除状态，否则新启动的控制循环会立即退出
        self._stop_event.clear()
        self._pause_event.set()

        # 1. 停止旧的控制线程和进度线程
        self._stop_control_thread()
        self._stop_progress_thread()

        # 2. 在锁内清理进程并重置状态
        with self._state_lock:
            if self._playback_process:
                self._kill_process(self._playback_process)
                self._playback_process = None

            self._is_playing = True
            self._is_paused = False
            self._current_position = start_position
            self._paused_position = 0.0
            self._play_start_time = 0.0
            self._total_pause_time = 0.0
            self._pause_start_time = 0.0
            # 新的播放世代
            self._playback_generation += 1
            current_gen = self._playback_generation

        filepath = song['path']
        abs_filepath = os.path.abspath(filepath)
        file_exists = os.path.exists(abs_filepath)

        logger.info(f"[音乐] 文件路径: {filepath}")
        logger.info(f"[音乐] 绝对路径: {abs_filepath}")
        logger.info(f"[音乐] 文件存在: {file_exists}")

        if not file_exists:
            logger.warning(f"[音乐] 文件不存在: {abs_filepath}")
            self._publish_event("stop", {"current_song": song})
            return

        player_cmd = self._find_player_command()

        if player_cmd is None:
            logger.error("[音乐] 未找到可用的音乐播放器")
            self._publish_event("stop", {"current_song": song})
            return

        try:
            full_cmd = [player_cmd]
            exe_name = os.path.basename(player_cmd).lower()

            # 构建 seek 参数（仅 mpv/ffplay 支持，用于恢复进度）
            seek_args = []
            if start_position > 0:
                if "mpv" in exe_name:
                    seek_args = ["--start=" + str(int(start_position))]
                elif "ffplay" in exe_name:
                    seek_args = ["-ss", str(int(start_position))]
                elif "vlc" in exe_name:
                    seek_args = ["--start-time=" + str(int(start_position))]

            if exe_name == "aplay":
                full_cmd.append("-q")
            elif exe_name == "afplay":
                if self._player_supports_volume:
                    full_cmd.extend(["-v", str(self._volume / 100.0)])
            elif "mpv" in exe_name:
                # 配置 IPC socket，用于运行时音量调节（无需中断播放）
                # socket 路径包含 PID 和世代号，确保每次播放使用独立 socket
                current_gen_for_ipc = current_gen
                ipc_path = f"/tmp/smart_speaker_mpv_{os.getpid()}_{current_gen_for_ipc}.sock"
                try:
                    if os.path.exists(ipc_path):
                        os.unlink(ipc_path)
                except Exception:
                    pass
                self._mpv_ipc_socket = ipc_path
                full_cmd.extend([
                    "--no-terminal",
                    "--quiet",
                    "--volume", str(self._volume),
                    f"--input-ipc-server={ipc_path}",
                ])
            elif "ffplay" in exe_name:
                full_cmd.extend([
                    "-nodisp",
                    "-autoexit",
                    "-hide_banner",
                ])
            elif "mpg123" in exe_name:
                full_cmd.extend(["-q"])
            elif "vlc" in exe_name:
                full_cmd.extend([
                    "--no-one-instance",
                    "--no-playlist-enqueue",
                    "--quiet",
                ])

            # seek 参数插入到文件路径之前
            full_cmd.extend(seek_args)
            full_cmd.append(abs_filepath)

            logger.info(f"[音乐] 开始播放: {' '.join(full_cmd)}")
            new_process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            )

            with self._state_lock:
                # 再次确认世代未被stop覆盖
                if current_gen != self._playback_generation:
                    # 期间被stop了，杀掉新进程
                    self._kill_process(new_process)
                    return
                self._playback_process = new_process

            # 启动控制线程（带世代标记）
            self._control_thread = threading.Thread(
                target=self._playback_control_loop,
                args=(current_gen,),
                daemon=True,
                name=f"MusicControl-{current_gen}"
            )
            self._control_thread.start()

            # 立即设置播放起始时间，再做耗时的duration探测
            self._play_start_time = time.time() - start_position
            # 异步探测时长，不阻塞进度线程启动
            duration = self._get_song_duration(abs_filepath)
            if duration > 0:
                with self._state_lock:
                    if current_gen == self._playback_generation:
                        self._current_duration = duration

            # 启动进度跟踪线程
            self._progress_stop_event.clear()
            self._progress_thread = threading.Thread(
                target=self._progress_tracking_loop,
                daemon=True,
                name="MusicProgress"
            )
            self._progress_thread.start()

            self._publish_event("play", {"song": song, "volume": self._volume})

        except Exception as e:
            logger.error(f"[音乐] 启动播放器失败: {e}")
            self._publish_event("stop", {"current_song": song})

    def play(self, song_info: Optional[Dict] = None):
        self._stop_event.clear()
        self._pause_event.set()

        with self._state_lock:
            # 空库检查优先
            if self._library.count == 0:
                logger.warning("[音乐] 音乐库为空")
                return

            if song_info:
                matched = False
                for i, song in enumerate(self._library.songs):
                    if song['path'] == song_info['path']:
                        self._current_song_index = i
                        matched = True
                        break
                if not matched:
                    logger.warning(f"[音乐] 库中未找到: {song_info.get('path')}")

            if self._current_song_index < 0 or self._current_song_index >= self._library.count:
                self._current_song_index = 0

            song = self._library.songs[self._current_song_index]

        self._play_song(song)

    def pause(self):
        with self._state_lock:
            if self._is_paused or not self._is_playing:
                return

            self._is_playing = False
            self._is_paused = True
            self._pause_event.clear()
            self._pause_start_time = time.time()
            # 保存当前位置用于非Linux恢复
            self._paused_position = self._current_position

            # Linux下使用SIGSTOP暂停进程，保留播放进度
            if self._playback_process and platform.system() == "Linux":
                try:
                    os.kill(self._playback_process.pid, signal.SIGSTOP)
                    logger.info("[音乐] 已暂停（SIGSTOP，保留进度）")
                    self._publish_event("pause", {"current_song": self.current_song})
                    return
                except Exception as e:
                    logger.warning(f"[音乐] SIGSTOP失败，回退到终止进程: {e}")

            # 非Linux：杀进程但保留位置，resume时会从该位置继续
            if self._playback_process:
                self._kill_process(self._playback_process)
                self._playback_process = None

        logger.info(f"[音乐] 已暂停，位置={self._paused_position:.1f}s")
        self._publish_event("pause", {"current_song": self.current_song})

    def resume(self):
        with self._state_lock:
            if not self._is_paused:
                return

            self._is_paused = False
            self._is_playing = True
            self._pause_event.set()

            # 累计暂停时长，用于进度计算
            if self._pause_start_time > 0:
                self._total_pause_time += time.time() - self._pause_start_time
                self._pause_start_time = 0.0

            # Linux下使用SIGCONT恢复进程
            if self._playback_process and platform.system() == "Linux":
                try:
                    os.kill(self._playback_process.pid, signal.SIGCONT)
                    logger.info("[音乐] 已恢复（SIGCONT）")
                    self._publish_event("resume", {"current_song": self.current_song})
                    return
                except Exception as e:
                    logger.warning(f"[音乐] SIGCONT失败，重新播放: {e}")

            # 非Linux：重新启动播放，从暂停位置继续
            resume_pos = self._paused_position
            current_song = self.current_song

        # 锁外启动播放（避免在锁内调用_play_song造成死锁）
        if current_song:
            self._play_song(current_song, start_position=resume_pos)
            self._publish_event("resume", {"current_song": current_song})

    def toggle(self):
        """切换播放/暂停状态"""
        with self._state_lock:
            if self._is_paused:
                # 恢复播放
                self._is_paused = False
                self._is_playing = True
                self._pause_event.set()

                if self._pause_start_time > 0:
                    self._total_pause_time += time.time() - self._pause_start_time
                    self._pause_start_time = 0.0

                if self._playback_process and platform.system() == "Linux":
                    try:
                        os.kill(self._playback_process.pid, signal.SIGCONT)
                        logger.info("[音乐] 切换为播放状态（SIGCONT）")
                        self._publish_event("resume", {"current_song": self.current_song})
                        return "playing"
                    except Exception as e:
                        logger.warning(f"[音乐] SIGCONT失败，重新播放: {e}")

                # 非Linux回退：锁外启动播放
                resume_pos = self._paused_position
                current_song = self.current_song

                if current_song:
                    threading.Thread(
                        target=self._play_song,
                        args=(current_song, resume_pos),
                        daemon=True
                    ).start()
                self._publish_event("resume", {"current_song": current_song})
                return "playing"

            elif self._is_playing:
                # 暂停播放
                self._is_playing = False
                self._is_paused = True
                self._pause_event.clear()
                self._pause_start_time = time.time()
                self._paused_position = self._current_position

                if self._playback_process and platform.system() == "Linux":
                    try:
                        os.kill(self._playback_process.pid, signal.SIGSTOP)
                        logger.info("[音乐] 切换为暂停状态（SIGSTOP）")
                        self._publish_event("pause", {"current_song": self.current_song})
                        return "paused"
                    except Exception as e:
                        logger.warning(f"[音乐] SIGSTOP失败: {e}")

                if self._playback_process:
                    self._kill_process(self._playback_process)
                    self._playback_process = None

                logger.info(f"[音乐] 切换为暂停状态，位置={self._paused_position:.1f}s")
                self._publish_event("pause", {"current_song": self.current_song})
                return "paused"

            else:
                # 未播放，开始播放（保留当前索引，不强制重置为0）
                if self._library.count > 0:
                    if self._current_song_index < 0:
                        self._current_song_index = 0
                    # 同步设置播放状态，避免竞态
                    self._is_playing = True
                    self._is_paused = False
                    threading.Thread(target=self.play, daemon=True).start()
                    return "playing"
                return "stopped"

    def stop(self):
        with self._state_lock:
            self._stop_event.set()
            self._pause_event.set()
            self._progress_stop_event.set()
            # 递增世代使控制线程退出
            self._playback_generation += 1

            if self._playback_process:
                self._kill_process(self._playback_process)
                self._playback_process = None

            self._is_playing = False
            self._is_paused = False
            self._current_position = 0
            self._current_duration = 0
            self._play_start_time = 0.0
            self._total_pause_time = 0.0
            self._pause_start_time = 0.0
            self._paused_position = 0.0

        # 锁外join线程，避免持锁等待
        if self._control_thread and self._control_thread.is_alive():
            if self._control_thread is not threading.current_thread():
                self._control_thread.join(timeout=2)
        self._control_thread = None

        if self._progress_thread and self._progress_thread.is_alive():
            self._progress_thread.join(timeout=2)
        self._progress_thread = None

        logger.info("[音乐] 已停止")
        self._publish_event("stop", {"current_song": self.current_song})

    def next(self):
        with self._state_lock:
            if self._library.count == 0:
                return None

            self._stop_event.set()
            self._progress_stop_event.set()
            self._playback_generation += 1

            if self._playback_process:
                self._kill_process(self._playback_process)
                self._playback_process = None

            self._current_song_index = (self._current_song_index + 1) % self._library.count
            song = self._library.songs[self._current_song_index]

        # 锁外清理线程
        if self._control_thread and self._control_thread.is_alive():
            if self._control_thread is not threading.current_thread():
                self._control_thread.join(timeout=2)
        self._control_thread = None

        if self._progress_thread and self._progress_thread.is_alive():
            self._progress_thread.join(timeout=2)
        self._progress_thread = None

        self._stop_event.clear()
        self._progress_stop_event.clear()
        self._play_song(song)
        return song

    def previous(self):
        with self._state_lock:
            if self._library.count == 0:
                return None

            self._stop_event.set()
            self._progress_stop_event.set()
            self._playback_generation += 1

            if self._playback_process:
                self._kill_process(self._playback_process)
                self._playback_process = None

            self._current_song_index = (self._current_song_index - 1) % self._library.count
            song = self._library.songs[self._current_song_index]

        # 锁外清理线程
        if self._control_thread and self._control_thread.is_alive():
            if self._control_thread is not threading.current_thread():
                self._control_thread.join(timeout=2)
        self._control_thread = None

        if self._progress_thread and self._progress_thread.is_alive():
            self._progress_thread.join(timeout=2)
        self._progress_thread = None

        self._stop_event.clear()
        self._progress_stop_event.clear()
        self._play_song(song)
        return song

    def set_volume(self, volume: int):
        with self._state_lock:
            old_volume = self._volume
            self._volume = max(0, min(100, volume))
            new_volume = self._volume

        # 音量未变化，仅同步事件
        if old_volume == new_volume:
            self._publish_event("volume", {"volume": new_volume})
            return

        logger.info(f"[音乐] 音量设置为: {new_volume}%")

        # mpv：通过 IPC 即时调节音量，无需中断播放（可高频调用，无副作用）
        # 其他播放器（ffplay/mpg123/aplay等）：不支持运行时调节，
        #   新音量会在下一次播放（切歌/暂停恢复）时自动生效，避免重启导致的卡顿和杂音
        applied = self._try_mpv_runtime_volume(new_volume)
        if not applied:
            logger.debug(f"[音乐] 当前播放器不支持运行时音量调节，新音量将在下次播放时生效")

        self._publish_event("volume", {"volume": new_volume})

    def _try_mpv_runtime_volume(self, volume: int) -> bool:
        """通过 IPC socket 运行时调节 mpv 音量，无需中断播放。

        仅在播放器为 mpv 且 IPC socket 已就绪时生效。
        """
        player_cmd = self._player_cmd
        if not player_cmd or "mpv" not in os.path.basename(player_cmd).lower():
            return False

        socket_path = self._mpv_ipc_socket
        if not socket_path:
            return False

        try:
            import socket as _socket
            import json as _json
            # 等待 socket 就绪（mpv 启动后需要一点时间创建 socket）
            for _ in range(5):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.1)
            if not os.path.exists(socket_path):
                return False

            s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect(socket_path)
            cmd = _json.dumps({"command": ["set_property", "volume", volume]}) + "\n"
            s.sendall(cmd.encode())
            s.close()
            logger.info(f"[音乐] 通过 IPC 设置 mpv 音量: {volume}%")
            return True
        except Exception as e:
            logger.debug(f"[音乐] mpv IPC 音量调节失败: {e}")
            return False

    def get_progress(self) -> Dict:
        """线程安全地获取当前播放进度"""
        with self._state_lock:
            return {
                "position": round(self._current_position, 1),
                "duration": round(self._current_duration, 1),
                "is_playing": self._is_playing,
                "is_paused": self._is_paused,
            }

    def _publish_event(self, event_type: str, data: Dict) -> None:
        if self._bus:
            try:
                from ..core.message_bus import Event, EventType
                et_map = {
                    "play": EventType.MUSIC_PLAY,
                    "pause": EventType.MUSIC_PAUSE,
                    "resume": EventType.MUSIC_RESUME,
                    "stop": EventType.MUSIC_STOP,
                    "next": EventType.MUSIC_NEXT,
                    "previous": EventType.MUSIC_PREVIOUS,
                    "volume": EventType.MUSIC_VOLUME,
                }
                et = et_map.get(event_type, EventType.MUSIC_STOP)
                self._bus.publish(
                    Event(
                        event_type=et,
                        data=data,
                        source="MusicPlayer",
                    )
                )
            except Exception as e:
                logger.warning(f"发布音乐事件失败: {e}")

    def search(self, keyword: str) -> List[Dict]:
        return self._library.search(keyword)

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def current_song(self) -> Optional[Dict]:
        if 0 <= self._current_song_index < self._library.count:
            return self._library.songs[self._current_song_index]
        return None

    @property
    def library_count(self) -> int:
        return self._library.count

    @property
    def current_position(self) -> float:
        return self._current_position

    @property
    def current_duration(self) -> float:
        return self._current_duration