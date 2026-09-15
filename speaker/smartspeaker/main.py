"""
USTB AI Speaker - 统一入口
============================

使用方式：
    cd speaker/smartspeaker
    python main.py              # 默认：融合模式（语音核心 + 科幻仪表盘）
    python main.py --preview    # 预览模式：仅UI界面，无语音核心
    python main.py --cli        # 命令行模式：仅语音核心，无UI
    python main.py --browser    # 浏览器模式：语音核心 + HTTP + Firefox

目录结构：
    speaker/
    ├── data/                   # 数据（日志、音乐）- 音箱本地保持不动
    ├── models/                 # AI模型（ASR、TTS、LLM）- 音箱本地保持不动
    └── smartspeaker/
        ├── main.py             # ← 本文件
        ├── src/                # 语音核心代码
        ├── dashboard/          # 仪表盘引擎
        └── web/                # 前端资源
"""

import sys
import os
import threading
import time
import traceback
import argparse
import subprocess
import platform

# smartspeaker 目录路径（本文件所在目录）
SMARTSPEAKER_DIR = os.path.abspath(os.path.dirname(__file__))
# 项目根目录 = speaker/（包含 data、models、smartspeaker）
PROJECT_ROOT = os.path.dirname(SMARTSPEAKER_DIR)

# 添加路径
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SMARTSPEAKER_DIR)

# 全局事件，用于优雅关闭
SHUTDOWN_EVENT = threading.Event()

# 语音核心应用实例（后台线程运行）
VOICE_APP = None
VOICE_THREAD = None

# HTTP 服务器线程
HTTP_THREAD = None
HTTP_PORT = 8080


def _force_exit_after_delay(delay: float = 10.0):
    """延迟强制退出兜底：防止优雅关闭超时卡死"""
    def _exit():
        time.sleep(delay)
        if not SHUTDOWN_EVENT.is_set():
            print(f"\n[强制退出] 优雅关闭超时({delay}s)，强制终止进程")
            os._exit(1)
    t = threading.Thread(target=_exit, daemon=True)
    t.start()


def _run_voice_core():
    """在后台线程中运行语音核心服务。"""
    global VOICE_APP

    print("[VoiceCore] 启动语音核心服务...")

    try:
        if VOICE_APP is None:
            raise RuntimeError("VoiceCore 未初始化")

        VOICE_APP.start(enable_microphone=True)

        print("[VoiceCore] 语音核心服务启动完成")
        print(f"[VoiceCore] 唤醒词: {VOICE_APP.config.audio.wake_word}")
        print(f"[VoiceCore] WebSocket: ws://localhost:8765")

        while not SHUTDOWN_EVENT.is_set():
            time.sleep(0.1)

    except Exception as e:
        print(f"\n[VoiceCore] 语音核心启动失败: {e}")
        traceback.print_exc()
    finally:
        print("[VoiceCore] 正在关闭语音核心...")
        if VOICE_APP:
            try:
                VOICE_APP.stop()
            except Exception as e:
                print(f"[VoiceCore] 关闭时出错: {e}")
        print("[VoiceCore] 语音核心已关闭")


def _init_voice_core():
    """在主线程初始化语音核心（避免 asyncio 事件循环问题）。"""
    global VOICE_APP

    print("[VoiceCore] 初始化语音核心...")

    try:
        from src.app import SmartSpeakerApp

        VOICE_APP = SmartSpeakerApp()
        # 注册语音退出回调：当 DialogManager 收到"退出/再见"等指令时，
        # 通过消息总线触发 SHUTDOWN_EVENT.set()，让主循环退出
        VOICE_APP.on_shutdown_request = lambda: SHUTDOWN_EVENT.set()
        print("[VoiceCore] 语音核心初始化完成（已注册语音退出回调）")
        return VOICE_APP

    except Exception as e:
        print(f"\n[VoiceCore] 语音核心初始化失败: {e}")
        traceback.print_exc()
        return None


def _start_http_server(web_dir: str, port: int = 8080):
    """启动本地 HTTP 服务器，用于浏览器访问仪表盘"""
    import http.server
    import socketserver

    os.chdir(web_dir)
    Handler = http.server.SimpleHTTPRequestHandler

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    httpd = ReusableTCPServer(("", port), Handler)
    print(f"[HTTP Server] 启动: http://localhost:{port}")

    while not SHUTDOWN_EVENT.is_set():
        httpd.handle_request()

    httpd.server_close()
    print("[HTTP Server] 已关闭")


def _open_firefox(url: str, fullscreen: bool = True):
    """使用 Firefox 打开仪表盘"""
    try:
        cmd = ["firefox", "--new-window"]
        if fullscreen:
            cmd.append("--kiosk")
        cmd.append(url)

        print(f"[Firefox] 启动: {' '.join(cmd)}")
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("[Firefox] 已启动")
        return True

    except FileNotFoundError:
        print("[Firefox] 未找到 firefox 命令")
        return False
    except Exception as e:
        print(f"[Firefox] 启动失败: {e}")
        return False


def _open_chromium(url: str, fullscreen: bool = True):
    """使用 Chromium/Chrome 打开仪表盘"""
    for browser_cmd in ["chromium-browser", "chromium", "google-chrome", "chrome"]:
        try:
            cmd = [browser_cmd, "--new-window"]
            if fullscreen:
                cmd.append("--kiosk")
            cmd.append(url)

            print(f"[Browser] 尝试启动: {' '.join(cmd)}")
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[Browser] {browser_cmd} 已启动")
            return True

        except FileNotFoundError:
            continue
        except Exception as e:
            print(f"[Browser] {browser_cmd} 启动失败: {e}")
            continue

    print("[Browser] 未找到任何支持的浏览器")
    return False


def _run_dashboard_with_fallback(web_dir: str, http_port: int = 8080):
    """
    尝试多种方式启动仪表盘：
    1. 优先尝试 pywebview（Windows/macOS 体验最好）
    2. Linux 下 pywebview 失败时，启动 HTTP + Firefox/Chromium
    3. 全部失败时提示手动打开浏览器
    """
    url = f"http://localhost:{http_port}"

    # 先启动 HTTP 服务器（供浏览器访问）
    global HTTP_THREAD
    HTTP_THREAD = threading.Thread(
        target=_start_http_server,
        args=(web_dir, http_port),
        daemon=True,
    )
    HTTP_THREAD.start()

    # 等待 HTTP 服务器启动
    time.sleep(1)

    # 尝试 pywebview（如果可用）
    try:
        from dashboard.main_window import run_dashboard

        print("[Dashboard] 尝试启动 pywebview 仪表盘...")
        run_dashboard(kiosk=True)
        return

    except ImportError:
        print("[Dashboard] pywebview 未安装")
    except Exception as e:
        print(f"[Dashboard] pywebview 启动失败: {e}")

    # pywebview 失败，尝试 Firefox
    print("[Dashboard] 尝试使用 Firefox 打开仪表盘...")
    if _open_firefox(url, fullscreen=True):
        print(f"[Dashboard] 仪表盘已在 Firefox 中打开: {url}")
        print("[Dashboard] 关闭 Firefox 窗口即可退出")

        # 等待关闭信号
        while not SHUTDOWN_EVENT.is_set():
            time.sleep(0.5)
        return

    # Firefox 失败，尝试 Chromium/Chrome
    print("[Dashboard] 尝试使用 Chromium/Chrome 打开仪表盘...")
    if _open_chromium(url, fullscreen=True):
        print(f"[Dashboard] 仪表盘已在浏览器中打开: {url}")
        print("[Dashboard] 关闭浏览器窗口即可退出")

        while not SHUTDOWN_EVENT.is_set():
            time.sleep(0.5)
        return

    # 全部失败，提示手动打开
    print("=" * 60)
    print("  仪表盘启动失败")
    print("=" * 60)
    print()
    print(f"HTTP 服务器已启动: {url}")
    print("请手动在浏览器中打开上述地址")
    print()
    print("按 Ctrl+C 退出...")
    print()

    try:
        while not SHUTDOWN_EVENT.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


def _run_dashboard_only():
    """仅运行仪表盘UI（预览模式），不启动语音核心"""
    print("=" * 60)
    print("  USTB AI Speaker - 科幻仪表盘预览模式")
    print("=" * 60)
    print()

    web_dir = os.path.join(SMARTSPEAKER_DIR, "web")
    _run_dashboard_with_fallback(web_dir, http_port=HTTP_PORT)


def _run_cli_mode():
    """仅运行语音核心（命令行模式），无UI界面"""
    print("=" * 60)
    print("  USTB AI Speaker - 命令行模式")
    print("=" * 60)
    print()

    try:
        from src.app import SmartSpeakerApp

        app = SmartSpeakerApp()
        # CLI 模式也注册语音退出回调
        app.on_shutdown_request = lambda: SHUTDOWN_EVENT.set()
        app.start(enable_microphone=True)

        print("[VoiceCore] 语音核心启动完成")
        print(f"唤醒词: {app.config.audio.wake_word}")
        print("\n按 Ctrl+C 退出...")

        try:
            while not SHUTDOWN_EVENT.is_set():
                time.sleep(0.1)
            print("\n收到语音退出指令，正在关闭...")
        except KeyboardInterrupt:
            print("\n收到退出信号...")

    except Exception as e:
        print(f"[ERROR] 启动失败: {e}")
        traceback.print_exc()
        sys.exit(1)


def _run_browser_mode():
    """浏览器模式：启动语音核心 + HTTP服务器，通过浏览器访问仪表盘"""
    global VOICE_THREAD, VOICE_APP

    print("=" * 60)
    print("  USTB AI Speaker - 浏览器模式")
    print("=" * 60)
    print()

    voice_app = _init_voice_core()
    if voice_app is None:
        print("[ERROR] 语音核心初始化失败，退出")
        sys.exit(1)

    VOICE_THREAD = threading.Thread(target=_run_voice_core, daemon=False)
    VOICE_THREAD.start()

    time.sleep(3)

    web_dir = os.path.join(SMARTSPEAKER_DIR, "web")
    _run_dashboard_with_fallback(web_dir, http_port=HTTP_PORT)

    # 清理
    SHUTDOWN_EVENT.set()
    if VOICE_THREAD and VOICE_THREAD.is_alive():
        VOICE_THREAD.join(timeout=8)
    print("[System] 系统已关闭")
    sys.exit(0)


def main():
    """统一入口主函数"""
    global VOICE_THREAD

    parser = argparse.ArgumentParser(description="USTB AI Speaker")
    parser.add_argument(
        "--mode", "-m",
        choices=["fusion", "preview", "cli", "browser"],
        default="fusion",
        help="运行模式: fusion(融合) / preview(仅UI) / cli(仅命令行) / browser(浏览器)"
    )
    args = parser.parse_args()

    if args.mode == "preview":
        _force_exit_after_delay(15.0)
        _run_dashboard_only()

    elif args.mode == "cli":
        _run_cli_mode()

    elif args.mode == "browser":
        _run_browser_mode()

    else:
        print("=" * 60)
        print("  USTB AI Speaker - 融合模式")
        print("=" * 60)
        print()

        voice_app = _init_voice_core()
        if voice_app is None:
            print("[ERROR] 语音核心初始化失败，退出")
            sys.exit(1)

        # 注册全局音乐事件处理（解决多实例状态不同步问题）
        _register_music_handlers(voice_app)

        VOICE_THREAD = threading.Thread(target=_run_voice_core, daemon=False)
        VOICE_THREAD.start()

        time.sleep(3)

        web_dir = os.path.join(SMARTSPEAKER_DIR, "web")
        _run_dashboard_with_fallback(web_dir, http_port=HTTP_PORT)

        # 清理
        print("[System] 仪表盘已关闭，正在关闭语音核心...")
        SHUTDOWN_EVENT.set()
        if VOICE_THREAD and VOICE_THREAD.is_alive():
            VOICE_THREAD.join(timeout=8)
        print("[System] 系统已关闭")
        sys.exit(0)


def _register_music_handlers(voice_app):
    """注册全局音乐事件处理（确保所有控制信号都作用于同一个 MusicPlayer 实例）

    注意：player 内部操作（play/pause/stop 等）会通过 _publish_event 发布事件，
    这些是"状态通知"，不应再次触发 player 操作，否则会递归重复播放。
    只有来自 WebSocket/UI 的"外部请求"事件才需要调用 player 方法。
    区分方法：
      - 外部请求：event.data 带 "song_index" 字段（music_play）或来自 WebSocket 消息
      - 内部通知：event.data 不带 "song_index"（player._publish_event 发布的）
    """
    from src.core.message_bus import EventType, Event
    from src.audio.player_manager import get_player_manager

    bus = voice_app.message_bus
    manager = get_player_manager()
    player = manager.get_player()

    def on_play(event):
        try:
            # 只处理来自 WebSocket 的外部请求（带 song_index）
            # player 内部发布的 MUSIC_PLAY 通知没有 song_index，忽略避免递归
            song_index = event.data.get("song_index")
            if song_index is None:
                return
            if song_index >= 0:
                songs = player._library.songs
                if 0 <= song_index < len(songs):
                    song = songs[song_index]
                    player.play(song)
        except Exception as e:
            print(f"[Music] Play error: {e}")

    def on_pause(event):
        try:
            # 幂等检查：已在暂停或未播放时忽略
            if getattr(player, '_is_paused', False) or not getattr(player, '_is_playing', False):
                return
            player.pause()
        except Exception as e:
            print(f"[Music] Pause error: {e}")

    def on_stop(event):
        try:
            # 幂等检查：未播放且未暂停时忽略
            if not getattr(player, '_is_playing', False) and not getattr(player, '_is_paused', False):
                return
            player.stop()
        except Exception as e:
            print(f"[Music] Stop error: {e}")

    def on_resume(event):
        try:
            # 幂等检查：非暂停状态时忽略（player.resume 内部也有此检查）
            if not getattr(player, '_is_paused', False):
                return
            player.resume()
        except Exception as e:
            print(f"[Music] Resume error: {e}")

    def on_toggle(event):
        try:
            result = player.toggle()
            print(f"[Music] Toggle result: {result}")
        except Exception as e:
            print(f"[Music] Toggle error: {e}")

    def on_next(event):
        try:
            # player.next() 不发布 MUSIC_NEXT 事件，不会递归
            player.next()
        except Exception as e:
            print(f"[Music] Next error: {e}")

    def on_prev(event):
        try:
            player.previous()
        except Exception as e:
            print(f"[Music] Prev error: {e}")

    bus.subscribe(EventType.MUSIC_PLAY, on_play, "global_music_handler", priority=5)
    bus.subscribe(EventType.MUSIC_PAUSE, on_pause, "global_music_handler", priority=5)
    bus.subscribe(EventType.MUSIC_STOP, on_stop, "global_music_handler", priority=5)
    bus.subscribe(EventType.MUSIC_RESUME, on_resume, "global_music_handler", priority=5)
    bus.subscribe(EventType.MUSIC_TOGGLE, on_toggle, "global_music_handler", priority=5)
    bus.subscribe(EventType.MUSIC_NEXT, on_next, "global_music_handler", priority=5)
    bus.subscribe(EventType.MUSIC_PREV, on_prev, "global_music_handler", priority=5)
    bus.subscribe(EventType.MUSIC_PREVIOUS, on_prev, "global_music_handler", priority=5)
    print("[System] 全局音乐事件处理器已注册（使用单例 MusicPlayer，防递归）")


if __name__ == "__main__":
    main()