import subprocess
import threading
import socket
import os
import time
import signal
import sys
from typing import Optional

from ..skills.base import BaseSkill, SkillResult
from ..utils.logger import logger


class FruitNinjaSkill(BaseSkill):
    def __init__(self):
        super().__init__("fruit_ninja", "启动水果忍者游戏")
        self._proc = None
        self._port_http = None
        self._port_ws = None
        self._heartbeat_thread = None
        self._game_dir = self._resolve_game_dir()
        logger.info(f"[FruitNinjaSkill] 游戏目录: {self._game_dir}")

    def _resolve_game_dir(self) -> str:
        """智能探测游戏目录，支持多种启动方式"""
        # 方案1: 基于 __file__ 的相对路径（最可靠）
        file_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = []

        # 向上探测4层目录
        for _ in range(4):
            file_dir = os.path.dirname(file_dir)
            candidate = os.path.join(file_dir, "LinuxFruitV2")
            candidates.append(candidate)

        # 方案2: 基于当前工作目录
        cwd = os.getcwd()
        candidates.append(os.path.join(cwd, "LinuxFruitV2"))
        # 如果当前在 smartspeaker 目录内
        if os.path.basename(cwd) == "smartspeaker-src":
            candidates.append(os.path.join(os.path.dirname(cwd), "LinuxFruitV2"))

        # 方案3: 环境变量覆盖
        env_dir = os.environ.get("FRUIT_NINJA_DIR")
        if env_dir:
            candidates.insert(0, env_dir)

        # 验证哪个目录有效
        for candidate in candidates:
            game_server = os.path.join(candidate, "game_server.py")
            if os.path.isfile(game_server):
                logger.info(f"[FruitNinjaSkill] 找到游戏目录: {candidate}")
                return candidate

        # 如果没有找到，返回第一个候选并记录警告
        logger.warning(f"[FruitNinjaSkill] 未找到 game_server.py，尝试路径: {candidates[0]}")
        logger.warning(f"[FruitNinjaSkill] 已尝试路径: {candidates}")
        return candidates[0]

    def can_handle(self, intent, entities):
        return intent == "fruit_ninja"

    def execute(self, intent, entities, context):
        text = entities.get("text", "")
        if "退出" in text or "关闭" in text:
            return self._stop()
        return self._start()

    def _find_port(self, start_port: int, max_tries: int = 20) -> int:
        for port in range(start_port, start_port + max_tries):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("", port))
                    return port
                except OSError:
                    continue
        raise RuntimeError(f"No available port starting from {start_port}")

    def _get_python_cmd(self) -> str:
        """获取Python命令，优先python3"""
        for cmd in ["python3", "python"]:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=2
                )
                if result.returncode == 0:
                    return cmd
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return "python3"  # 默认回退

    def _start(self) -> SkillResult:
        if self._proc is not None:
            return SkillResult(
                success=True,
                speak_text="游戏已经在运行中。"
            )

        # 预先检查游戏目录
        game_server_path = os.path.join(self._game_dir, "game_server.py")
        if not os.path.isfile(game_server_path):
            error_msg = (
                f"找不到 game_server.py\n"
                f"期望路径: {game_server_path}\n"
                f"当前工作目录: {os.getcwd()}\n"
                f"请确认 LinuxFruitV2 目录与 smartspeaker-src 同级"
            )
            logger.error(f"[FruitNinjaSkill] {error_msg}")
            return SkillResult(
                success=False,
                speak_text=f"游戏启动失败：找不到游戏文件，请检查目录结构。"
            )

        try:
            self._port_http = self._find_port(8081)
            self._port_ws = self._find_port(8766)
            logger.info(f"[FruitNinjaSkill] 分配端口 HTTP={self._port_http} WS={self._port_ws}")

            env = os.environ.copy()
            env["GAME_HTTP_PORT"] = str(self._port_http)
            env["GAME_WS_PORT"] = str(self._port_ws)
            env["SCREEN_WIDTH"] = "1920"
            env["SCREEN_HEIGHT"] = "1200"

            python_cmd = self._get_python_cmd()
            logger.info(f"[FruitNinjaSkill] 使用Python: {python_cmd}")

            cmd = [python_cmd, game_server_path]
            logger.info(f"[FruitNinjaSkill] 启动命令: {' '.join(cmd)}")
            logger.info(f"[FruitNinjaSkill] 工作目录: {self._game_dir}")

            # 使用 stdout/stderr 管道捕获日志，便于排查问题
            # 关键：POSIX 上使用 start_new_session=True 让游戏进入独立进程组/会话，
            # 这样 _stop() 调用 os.killpg() 时只会终止游戏及其子进程，
            # 不会误杀智能音箱主程序（之前 start_new_session=False 导致共享父进程组，
            # killpg 会连带杀死主程序）
            popen_kwargs = dict(
                env=env,
                cwd=self._game_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if os.name == "posix":
                popen_kwargs["start_new_session"] = True
            else:
                # Windows：使用独立进程组，配合 taskkill /T 终止进程树
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            self._proc = subprocess.Popen(cmd, **popen_kwargs)

            # 等待一小段时间检查进程是否立即退出
            time.sleep(1)
            retcode = self._proc.poll()
            if retcode is not None:
                stdout, stderr = "", ""
                try:
                    stdout, stderr = self._proc.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                error_detail = stderr or stdout or f"进程退出码: {retcode}"
                logger.error(f"[FruitNinjaSkill] 游戏进程立即退出: {error_detail}")
                self._proc = None
                return SkillResult(
                    success=False,
                    speak_text=f"游戏启动失败：{error_detail[:100]}"
                )

            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                daemon=True
            )
            self._heartbeat_thread.start()

            # 再等待一秒让服务器完全启动
            time.sleep(1)

            url = f"http://localhost:{self._port_http}"
            logger.info(f"[FruitNinjaSkill] 游戏URL: {url}")

            # 尝试打开浏览器
            self._open_browser(url)

            return SkillResult(
                success=True,
                speak_text="好的，正在为您启动水果忍者游戏。",
                data={"url": url}
            )

        except Exception as e:
            logger.exception("[FruitNinjaSkill] 启动异常")
            self._proc = None
            return SkillResult(
                success=False,
                speak_text=f"游戏启动失败：{str(e)}"
            )

    def _open_browser(self, url: str):
        """尝试打开浏览器，兼容 Linux/Windows/macOS"""
        if os.name == "posix":
            browsers = ["xdg-open", "chromium-browser", "chromium", "google-chrome", "firefox"]
            for browser in browsers:
                try:
                    subprocess.Popen(
                        [browser, url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    logger.info(f"[FruitNinjaSkill] 使用 {browser} 打开游戏")
                    return
                except FileNotFoundError:
                    continue
        else:
            # Windows：使用 start 命令通过默认浏览器打开
            try:
                subprocess.Popen(
                    ["cmd", "/c", "start", "", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                logger.info(f"[FruitNinjaSkill] 使用默认浏览器打开游戏")
                return
            except Exception as e:
                logger.debug(f"[FruitNinjaSkill] Windows 打开浏览器失败: {e}")
        logger.warning("[FruitNinjaSkill] 未找到可用浏览器，请手动打开: " + url)

    def _stop(self) -> SkillResult:
        if self._proc is None:
            return SkillResult(
                success=True,
                speak_text="游戏尚未启动。"
            )

        proc = self._proc
        try:
            self._terminate_game_process(proc)
        except Exception as e:
            logger.error(f"[FruitNinjaSkill] 停止游戏异常: {e}")
        finally:
            # 清理 IPC socket 文件
            self._cleanup_ipc_socket()
            self._proc = None

        # 切回音箱界面
        self._open_browser("http://localhost:8080")

        return SkillResult(
            success=True,
            speak_text="游戏已关闭。"
        )

    def _terminate_game_process(self, proc) -> None:
        """跨平台终止游戏进程及其子进程。

        POSIX：游戏进程在独立会话/进程组中（start_new_session=True），
              killpg 只会终止游戏进程组，不会波及智能音箱主程序。
        Windows：使用 taskkill /F /T 终止整个进程树。
        """
        if os.name == "posix":
            # 先 SIGTERM 优雅退出
            killed = False
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                killed = True
            except (ProcessLookupError, OSError) as e:
                logger.debug(f"[FruitNinjaSkill] SIGTERM 进程组失败，尝试 terminate: {e}")
                try:
                    proc.terminate()
                    killed = True
                except Exception:
                    pass

            if killed:
                try:
                    proc.wait(timeout=5)
                    return
                except subprocess.TimeoutExpired:
                    logger.warning("[FruitNinjaSkill] SIGTERM 超时，升级为 SIGKILL")
                    # SIGKILL 强制终止整个进程组
                    try:
                        pgid = os.getpgid(proc.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        proc.kill()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        logger.error("[FruitNinjaSkill] SIGKILL 后仍未退出")
        else:
            # Windows：taskkill /F /T 强制终止进程树
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception as e:
                logger.debug(f"[FruitNinjaSkill] taskkill 失败，回退到 terminate: {e}")
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    pass

    def _cleanup_ipc_socket(self) -> None:
        """清理可能的 mpv/游戏 IPC socket 文件（POSIX）"""
        # 当前 FruitNinjaSkill 不创建 IPC socket，此处保留扩展点
        pass

    def _heartbeat_loop(self):
        while True:
            proc = self._proc
            if proc is None:
                # 已被 _stop() 清理，无需再切回界面（_stop 会处理）
                break
            try:
                retcode = proc.poll()
                if retcode is not None:
                    logger.info(f"[FruitNinjaSkill] 游戏进程自行退出，码: {retcode}")
                    # 仅当 _proc 仍指向同一个进程时才清理（避免覆盖 _stop 的状态）
                    if self._proc is proc:
                        self._proc = None
                        self._open_browser("http://localhost:8080")
                    break
            except Exception as e:
                logger.debug(f"[FruitNinjaSkill] 心跳检查异常: {e}")
            time.sleep(3)

    def cleanup(self):
        self._stop()
