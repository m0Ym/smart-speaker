"""
系统遥测采集器 - SystemTelemetry
=================================
负责实时采集 CPU、内存、设备温度、WiFi 信号等系统数据。
通过定时器每隔 1 秒采集一次，并通过回调函数推送给前端。

依赖：psutil（CPU/内存），wmi（Windows 温度），subprocess（WiFi）
安装：pip install psutil pywifi
"""

import os
import sys
import time
import threading
from typing import Callable, Optional, Dict, Any


class SystemTelemetry:
    """
    系统遥测采集器。
    在独立线程中运行，定时采集系统数据并通过回调推送。
    """

    def __init__(self, callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 1.0  # 采集间隔（秒）

        # 缓存上次数据，用于平滑显示
        self._last_cpu = 0.0
        self._last_mem = 0.0
        self._last_temp = 0.0

    def start(self) -> None:
        """启动采集线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[Telemetry] 系统遥测采集已启动")

    def stop(self) -> None:
        """停止采集线程"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        print("[Telemetry] 系统遥测采集已停止")

    def _loop(self) -> None:
        """采集主循环，在独立线程中运行"""
        while self._running:
            try:
                data = self._collect()
                if self.callback:
                    self.callback(data)
            except Exception as e:
                print(f"[Telemetry] 采集异常: {e}")
            time.sleep(self._interval)

    def _collect(self) -> Dict[str, Any]:
        """采集一次系统数据"""
        data = {
            "cpu": self._get_cpu(),
            "memory": self._get_memory(),
            "temperature": self._get_temperature(),
            "wifi_rssi": self._get_wifi_rssi(),
        }
        return data

    def _get_cpu(self) -> float:
        """获取 CPU 使用率（1秒采样）"""
        try:
            import psutil
            # psutil.cpu_percent(interval=0.1) 会阻塞 0.1 秒采样
            val = psutil.cpu_percent(interval=0.1)
            self._last_cpu = val
            return val
        except ImportError:
            # psutil 未安装时返回模拟数据
            import random
            self._last_cpu = max(5, min(95, self._last_cpu + (random.random() - 0.5) * 10))
            return self._last_cpu
        except Exception:
            return self._last_cpu

    def _get_memory(self) -> float:
        """获取内存使用率"""
        try:
            import psutil
            mem = psutil.virtual_memory()
            self._last_mem = mem.percent
            return mem.percent
        except ImportError:
            import random
            self._last_mem = max(10, min(90, self._last_mem + (random.random() - 0.5) * 5))
            return self._last_mem
        except Exception:
            return self._last_mem

    def _get_temperature(self) -> float:
        """获取设备温度（摄氏度）"""
        try:
            import psutil
            # psutil 支持部分平台的温度传感器
            temps = psutil.sensors_temperatures()
            if temps:
                # 取第一个可用的温度读数
                for name, entries in temps.items():
                    if entries:
                        self._last_temp = entries[0].current
                        return self._last_temp
        except (ImportError, AttributeError):
            pass

        # Windows 下通过 wmi 获取（可选）
        if sys.platform == "win32":
            try:
                import wmi
                c = wmi.WMI(namespace="root\\wmi")
                for sensor in c.MSAcpi_ThermalZoneTemperature():
                    temp_k = sensor.CurrentTemperature
                    temp_c = (temp_k / 10.0) - 273.15
                    self._last_temp = temp_c
                    return temp_c
            except Exception:
                pass

        # 兜底：模拟数据
        import random
        self._last_temp = max(30, min(80, self._last_temp + (random.random() - 0.5) * 3))
        return self._last_temp

    def _get_wifi_rssi(self) -> int:
        """获取 WiFi 信号强度（dBm）"""
        try:
            if sys.platform == "win32":
                import subprocess
                result = subprocess.run(
                    ["netsh", "wlan", "show", "interfaces"],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.split("\n"):
                    if "信号" in line or "Signal" in line:
                        # 解析百分比并转换为 dBm 估算值
                        parts = line.split(":")
                        if len(parts) >= 2:
                            pct_str = parts[1].strip().replace("%", "")
                            try:
                                pct = int(pct_str)
                                # 0% ~ -90dBm, 100% ~ -30dBm
                                rssi = -90 + int(pct * 0.6)
                                return rssi
                            except ValueError:
                                pass
        except Exception:
            pass

        # 兜底
        return -50
