"""
仪表盘窗口 - Sci-Fi Dashboard Window (pywebview 版本)
=====================================================
使用 pywebview 加载本地 HTML5 仪表盘，配合全屏窗口打造沉浸式体验。

相比 PyQt6 的优势：
- 更轻量，无需额外安装 Qt 库
- 在 Windows 上默认使用 Edge (WebView2) 渲染引擎
- 自动支持现代 CSS3 / Canvas / WebGL 特效

依赖：pywebview
安装：pip install pywebview
"""

import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import webview


class DashboardAPI:
    """
    pywebview 的 JS API 桥接对象。
    前端通过 window.pywebview.api.xxx() 调用 Python 方法。
    """
    def __init__(self, voice_app=None):
        self.voice_app = voice_app

    def speak(self, text: str) -> str:
        """前端调用：请求语音播报"""
        print(f"[API] speak: {text}")
        return f"收到播报请求: {text}"

    def send_command(self, text: str) -> str:
        """前端调用：发送文本指令给语音核心"""
        print(f"[API] command: {text}")
        return f"收到指令: {text}"

    def get_system_info(self) -> dict:
        """前端调用：获取系统信息"""
        import platform
        return {
            "os": platform.system(),
            "version": platform.release(),
            "python": platform.python_version(),
        }


def _get_web_dir() -> Path:
    """获取 web 目录路径"""
    return Path(__file__).parent.parent / "web"


def run_dashboard(
    web_dir: Optional[str] = None,
    voice_app=None,
    fullscreen: bool = True,
    kiosk: bool = False,
) -> None:
    """
    启动科幻仪表盘窗口。

    参数:
        web_dir:    web 文件目录路径，默认使用内置 web/
        voice_app:  语音核心应用实例（可选，用于 API 桥接）
        fullscreen: 是否全屏显示
        kiosk:      Kiosk 模式（无窗口边框、置顶、防退出）
    """
    if web_dir is None:
        web_dir = _get_web_dir()
    else:
        web_dir = Path(web_dir)

    index_path = web_dir / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(
            f"仪表盘入口文件不存在: {index_path}\n"
            f"请确认 web/index.html 已正确放置。"
        )

    # 转换为 file:// URL
    url = f"file:///{index_path.resolve().as_posix()}"

    api = DashboardAPI(voice_app=voice_app)

    print(f"[Dashboard] 启动窗口: {url}")
    print(f"[Dashboard] 全屏: {fullscreen}, Kiosk: {kiosk}")

    # 创建窗口
    window = webview.create_window(
        title="USTB AI Speaker - Sci-Fi Dashboard",
        url=url,
        fullscreen=fullscreen,
        width=1920,
        height=1080,
        resizable=not kiosk,
        minimized=False,
        on_top=kiosk,
        confirm_close=not kiosk,  # Kiosk 模式下关闭无需确认
        js_api=api,
        background_color="#0A0A10",
        text_select=False,  # Kiosk 模式下禁止文本选中
    )

    import platform
    system = platform.system().lower()

    if system == "windows":
        engines = ["edgechromium", "mshtml"]
    elif system == "linux":
        engines = ["gtkwebkit2", "cef"]
    elif system == "darwin":
        engines = ["cocoa"]
    else:
        engines = []

    if not engines:
        raise RuntimeError(f"不支持的操作系统: {system}")

    for gui_engine in engines:
        try:
            webview.start(
                debug=False,
                gui=gui_engine,
                private_mode=False,
            )
            break
        except Exception as e:
            print(f"[Dashboard] {gui_engine} 引擎失败: {e}")
            if gui_engine == engines[-1]:
                raise

    print("[Dashboard] 窗口已关闭")


def run_dashboard_async(
    web_dir: Optional[str] = None,
    voice_app=None,
) -> webview.Window:
    """
    非阻塞方式启动仪表盘，返回窗口对象。
    需要在主线程中自行调用 webview.start() 启动事件循环。
    适用于需要同时运行其他逻辑的场景。
    """
    if web_dir is None:
        web_dir = _get_web_dir()
    else:
        web_dir = Path(web_dir)

    index_path = web_dir / "index.html"
    url = f"file:///{index_path.resolve().as_posix()}"

    api = DashboardAPI(voice_app=voice_app)

    window = webview.create_window(
        title="USTB AI Speaker - Sci-Fi Dashboard",
        url=url,
        fullscreen=True,
        width=1920,
        height=1080,
        resizable=False,
        on_top=True,
        confirm_close=False,
        js_api=api,
        background_color="#0A0A10",
        text_select=False,
    )

    return window
