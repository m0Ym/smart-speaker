"""
QWebChannel 桥接器 - WebChannelBridge
======================================
用于 PyQt6(QWebEngineView) 与前端 JavaScript 之间的双向通信。

虽然本系统主要使用 WebSocket 进行事件传输，但 QWebChannel
提供了另一种更直接的 Python ↔ JS 通信通道，适合：
- 前端直接调用 Python 函数（如获取系统信息）
- Python 直接调用前端 JS 函数（如触发特定动画）

使用方式：
    from PyQt6.QtWebChannel import QWebChannel
    bridge = WebChannelBridge()
    channel = QWebChannel()
    channel.registerObject("pybridge", bridge)
    webview.page().setWebChannel(channel)

前端 JS 中：
    new QWebChannel(qt.webChannelTransport, function(channel) {
        window.pybridge = channel.objects.pybridge;
        pybridge.speak("你好");  // 调用 Python 方法
    });
"""

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class WebChannelBridge(QObject):
    """
    QWebChannel 桥接对象。
    所有带有 @pyqtSlot 装饰器的方法都可以被前端 JS 直接调用。
    所有 pyqtSignal 都可以从前端发射并被 Python 接收。
    """

    # Python → JS 的信号（前端通过 connect 监听）
    speakSignal = pyqtSignal(str)       # 触发语音播报
    statusSignal = pyqtSignal(str, str) # 状态变化 (status, detail)
    toastSignal = pyqtSignal(str, str)  # Toast 提示 (msg, type)

    def __init__(self, parent=None):
        super().__init__(parent)

    @pyqtSlot(str)
    def speak(self, text: str) -> None:
        """
        前端调用：请求语音播报一段文本
        用法（JS）：pybridge.speak("你好")
        """
        print(f"[WebChannel] 收到语音播报请求: {text}")
        # 实际使用时，将请求转发给 smartspeakersrc 的 TTS 模块

    @pyqtSlot(str)
    def sendText(self, text: str) -> None:
        """
        前端调用：发送文本指令给语音核心
        用法（JS）：pybridge.sendText("播放音乐")
        """
        print(f"[WebChannel] 收到文本指令: {text}")
        # 实际使用时，转发给 smartspeakersrc 的对话管理器

    @pyqtSlot(str)
    def setStatus(self, status: str) -> None:
        """
        前端调用：手动设置仪表盘状态
        用法（JS）：pybridge.setStatus("listening")
        """
        print(f"[WebChannel] 状态切换: {status}")
        self.statusSignal.emit(status, "")

    @pyqtSlot(result=str)
    def getSystemInfo(self) -> str:
        """
        前端调用：获取系统基本信息
        用法（JS）：var info = pybridge.getSystemInfo()
        """
        import platform
        return f"{platform.system()} {platform.release()}"
