from __future__ import annotations
from typing import Any, Dict, Optional
import subprocess
import os
import re
import shlex
import shutil
from pathlib import Path

from .base import BaseSkill, SkillResult
from ..utils.logger import logger


class SystemCommandSkill(BaseSkill):
    def __init__(self) -> None:
        super().__init__("system_command", "执行系统命令，创建文件、文件夹、重命名等")
        # 跨平台允许目录
        home_dir = str(Path.home())
        self._allowed_dirs = [home_dir]
        if os.name == 'nt':
            # Windows：允许用户目录、临时目录
            self._allowed_dirs.append(os.environ.get('TEMP', ''))
            self._allowed_dirs.append(os.environ.get('TMP', ''))
        else:
            # Unix：允许 /home, /tmp, /var/tmp
            self._allowed_dirs.extend(["/home", "/tmp", "/var/tmp"])
        # 去重去空
        self._allowed_dirs = [d for d in self._allowed_dirs if d]
        # 命令白名单：run分支只允许执行这些命令
        self._command_whitelist = {
            "ls", "pwd", "cat", "echo", "date", "whoami", "uname",
            "df", "du", "head", "tail", "wc", "grep", "find",
            "ps", "top", "free", "uptime",
        }
        self._current_dir = home_dir

    def can_handle(self, intent: str, entities: Dict[str, Any]) -> bool:
        text = entities.get("text", "").lower()
        keywords = ["创建", "新建", "文件夹", "目录",
                    "重命名", "改名", "删除", "移除", "复制",
                    "移动", "列出", "切换目录", "进入目录",
                    "当前目录", "当前路径", "查看文件", "读取文件",
                    "写入文件", "执行命令", "运行命令", "权限",
                    "terminal", "shell", "linux"]
        return intent == "system_command" or any(kw in text for kw in keywords)

    def execute(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        text = entities.get("text", "")
        speak = ""
        success = True
        command_type = None

        try:
            command_type, args = self._parse_command(text)
            
            if command_type == "mkdir":
                dir_name = args.get("name", "")
                if dir_name:
                    full_path = self._get_full_path(dir_name)
                    if self._is_path_allowed(full_path):
                        os.makedirs(full_path, exist_ok=True)
                        speak = f"好的，已在{self._current_dir}创建文件夹'{dir_name}'。"
                    else:
                        speak = f"抱歉，该路径不在允许范围内。"
                        success = False
                else:
                    speak = "请告诉我要创建的文件夹名称。"
                    success = False

            elif command_type == "touch":
                file_name = args.get("name", "")
                if file_name:
                    full_path = self._get_full_path(file_name)
                    if self._is_path_allowed(full_path):
                        Path(full_path).touch()
                        speak = f"好的，已在{self._current_dir}创建文件'{file_name}'。"
                    else:
                        speak = f"抱歉，该路径不在允许范围内。"
                        success = False
                else:
                    speak = "请告诉我要创建的文件名称。"
                    success = False

            elif command_type == "rename":
                old_name = args.get("old_name", "")
                new_name = args.get("new_name", "")
                if old_name and new_name:
                    old_path = self._get_full_path(old_name)
                    new_path = self._get_full_path(new_name)
                    if self._is_path_allowed(old_path) and self._is_path_allowed(new_path):
                        os.rename(old_path, new_path)
                        speak = f"好的，已将'{old_name}'重命名为'{new_name}'。"
                    else:
                        speak = "抱歉，该路径不在允许范围内。"
                        success = False
                else:
                    speak = "请告诉我原名称和新名称。"
                    success = False

            elif command_type == "delete":
                name = args.get("name", "")
                if name:
                    full_path = self._get_full_path(name)
                    if self._is_path_allowed(full_path):
                        if os.path.isdir(full_path):
                            import shutil
                            shutil.rmtree(full_path)
                        else:
                            os.remove(full_path)
                        speak = f"好的，已删除'{name}'。"
                    else:
                        speak = "抱歉，该路径不在允许范围内。"
                        success = False
                else:
                    speak = "请告诉我要删除的文件或文件夹名称。"
                    success = False

            elif command_type == "copy":
                src_name = args.get("src_name", "")
                dest_name = args.get("dest_name", "")
                if src_name and dest_name:
                    src_path = self._get_full_path(src_name)
                    dest_path = self._get_full_path(dest_name)
                    if self._is_path_allowed(src_path) and self._is_path_allowed(dest_path):
                        if os.path.isdir(src_path):
                            import shutil
                            shutil.copytree(src_path, dest_path)
                        else:
                            shutil.copy2(src_path, dest_path)
                        speak = f"好的，已将'{src_name}'复制到'{dest_name}'。"
                    else:
                        speak = "抱歉，该路径不在允许范围内。"
                        success = False
                else:
                    speak = "请告诉我源文件和目标文件名称。"
                    success = False

            elif command_type == "move":
                src_name = args.get("src_name", "")
                dest_name = args.get("dest_name", "")
                if src_name and dest_name:
                    src_path = self._get_full_path(src_name)
                    dest_path = self._get_full_path(dest_name)
                    if self._is_path_allowed(src_path) and self._is_path_allowed(dest_path):
                        shutil.move(src_path, dest_path)
                        speak = f"好的，已将'{src_name}'移动到'{dest_name}'。"
                    else:
                        speak = "抱歉，该路径不在允许范围内。"
                        success = False
                else:
                    speak = "请告诉我源文件和目标文件名称。"
                    success = False

            elif command_type == "list":
                show_hidden = args.get("show_hidden", False)
                items = os.listdir(self._current_dir)
                if not show_hidden:
                    items = [i for i in items if not i.startswith('.')]
                if items:
                    items_str = ", ".join(items[:10])
                    if len(items) > 10:
                        items_str += f" 等{len(items)}个项目"
                    speak = f"当前目录有：{items_str}。"
                else:
                    speak = "当前目录为空。"

            elif command_type == "pwd":
                speak = f"当前目录是：{self._current_dir}。"

            elif command_type == "cd":
                dir_name = args.get("name", "")
                if dir_name == "home" or dir_name == "家目录":
                    self._current_dir = str(Path.home())
                    speak = "好的，已回到家目录。"
                elif dir_name:
                    new_path = self._get_full_path(dir_name)
                    if self._is_path_allowed(new_path) and os.path.isdir(new_path):
                        self._current_dir = new_path
                        speak = f"好的，已切换到目录'{dir_name}'。"
                    else:
                        speak = f"抱歉，目录'{dir_name}'不存在或不在允许范围内。"
                        success = False
                else:
                    speak = "请告诉我要切换到哪个目录。"
                    success = False

            elif command_type == "cat":
                file_name = args.get("name", "")
                if file_name:
                    full_path = self._get_full_path(file_name)
                    if self._is_path_allowed(full_path) and os.path.isfile(full_path):
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        if len(content) > 200:
                            content = content[:200] + "..."
                        speak = f"文件内容：{content}"
                    else:
                        speak = f"抱歉，文件'{file_name}'不存在或不在允许范围内。"
                        success = False
                else:
                    speak = "请告诉我要查看的文件名称。"
                    success = False

            elif command_type == "echo":
                content = args.get("content", "")
                file_name = args.get("file_name", "")
                if content:
                    if file_name:
                        full_path = self._get_full_path(file_name)
                        if self._is_path_allowed(full_path):
                            mode = 'a' if "追加" in text else 'w'
                            with open(full_path, mode, encoding='utf-8') as f:
                                f.write(content + '\n')
                            speak = f"好的，已将内容写入'{file_name}'。"
                        else:
                            speak = "抱歉，该路径不在允许范围内。"
                            success = False
                    else:
                        speak = f"内容是：{content}"
                else:
                    if not file_name:
                        speak = "请告诉我要输出的内容和文件名称。"
                    else:
                        speak = "请告诉我要输出的内容。"
                    success = False

            elif command_type == "chmod":
                file_name = args.get("name", "")
                perm = args.get("perm", "755")
                if file_name:
                    full_path = self._get_full_path(file_name)
                    if self._is_path_allowed(full_path):
                        os.chmod(full_path, int(perm, 8))
                        speak = f"好的，已将'{file_name}'权限设置为{perm}。"
                    else:
                        speak = "抱歉，该路径不在允许范围内。"
                        success = False
                else:
                    speak = "请告诉我要修改权限的文件名称。"
                    success = False

            elif command_type == "run":
                cmd = args.get("command", "")
                if cmd:
                    # 安全：用shlex分词并校验白名单，禁用shell=True
                    try:
                        parts = shlex.split(cmd)
                    except ValueError as e:
                        speak = f"命令解析失败：{str(e)}"
                        success = False
                        parts = None
                    if parts:
                        base_cmd = os.path.basename(parts[0])
                        if base_cmd in self._command_whitelist:
                            logger.info(f"[SystemCommand] Executing whitelisted: {base_cmd}")
                            try:
                                result = subprocess.run(
                                    parts, shell=False, capture_output=True, text=True,
                                    cwd=self._current_dir, timeout=30
                                )
                                output = result.stdout or result.stderr
                                if len(output) > 300:
                                    output = output[:300] + "..."
                                speak = f"命令执行结果：{output}"
                            except subprocess.TimeoutExpired:
                                speak = "命令执行超时。"
                                success = False
                            except Exception as e:
                                speak = f"命令执行失败：{str(e)}"
                                success = False
                        else:
                            speak = f"抱歉，不支持执行'{base_cmd}'命令。允许的命令：{', '.join(sorted(self._command_whitelist))}"
                            success = False
                else:
                    speak = "请告诉我要执行的命令。"
                    success = False

            else:
                speak = "抱歉，我不太明白您想要执行什么操作。"
                success = False

        except Exception as e:
            logger.error(f"[SystemCommand] Error: {e}")
            speak = f"执行失败：{str(e)}"
            success = False

        return SkillResult(
            success=success,
            data={
                "command_type": command_type,
                "current_dir": self._current_dir,
            },
            message=f"系统命令执行{'成功' if success else '失败'}",
            speak_text=speak,
        )

    def _parse_command(self, text: str) -> tuple:
        text = text.strip()

        # === 创建文件夹/目录 ===
        if re.search(r"(创建|新建|建个|建一个).*?(文件夹|目录)", text):
            # 优先匹配 "叫/为/名为 XXX" 的模式
            m = re.search(r"(?:叫|为|名为|名字叫|叫作)\s*([^\s。，、的]+)", text)
            if m:
                name = m.group(1).strip()
                if name and name not in ("一个", "个"):
                    return ("mkdir", {"name": name})
            # 匹配 "文件夹/目录 XXX" 或 "文件夹/目录XXX" (名称在后面，可有空格也可没有)
            m = re.search(r"(?:文件夹|目录)\s*([^\s。，、的]+)", text)
            if m:
                name = m.group(1).strip()
                if name and name not in ("叫", "为", "的"):
                    return ("mkdir", {"name": name})
            # 匹配 "创建XXX文件夹/目录" (名称在前面)
            m = re.search(r"(?:创建|新建|建个|建一个)(?:一个|个|个叫)?\s*([^\s。，、]+?)\s*(?:文件夹|目录)", text)
            if m:
                name = m.group(1).strip()
                if name and name not in ("一个", "个", "叫"):
                    return ("mkdir", {"name": name})
            return ("mkdir", {"name": ""})

        # === 创建文件 ===
        if re.search(r"(创建|新建|建个|建一个).*?文件", text):
            m = re.search(r"(?:叫|为|名为|名字叫)\s*([^\s。，、的]+)", text)
            if m:
                name = m.group(1).strip()
                if name and name not in ("一个", "个"):
                    return ("touch", {"name": name})
            m = re.search(r"文件\s*([^\s。，、的]+)", text)
            if m:
                name = m.group(1).strip()
                if name and name not in ("叫", "为", "的"):
                    return ("touch", {"name": name})
            m = re.search(r"(?:创建|新建|建个|建一个)(?:一个|个)?\s*([^\s。，、]+?)\s*文件", text)
            if m:
                name = m.group(1).strip()
                if name and name not in ("一个", "个"):
                    return ("touch", {"name": name})
            return ("touch", {"name": ""})

        # === 重命名 ===
        elif "重命名" in text or "改名" in text:
            match = re.search(r"(?:重命名|改名)\s*([^为成]+?)(?:为|成|叫)\s*([^。，、\s]+)", text)
            if match:
                old_name = match.group(1).strip()
                new_name = match.group(2).strip()
                return ("rename", {"old_name": old_name, "new_name": new_name})
            return ("rename", {"old_name": "", "new_name": ""})

        # === 删除 ===
        elif "删除" in text or "移除" in text:
            match = re.search(r"(?:删除|移除)\s*(?:文件|文件夹|目录)?\s*([^\s。，、]+)", text)
            name = match.group(1).strip() if match else ""
            return ("delete", {"name": name})

        # === 复制 ===
        elif "复制" in text:
            match = re.search(r"复制\s*(.+?)(?:到|为|至)\s*([^。，、\s]+)", text)
            if match:
                return ("copy", {"src_name": match.group(1).strip(), "dest_name": match.group(2).strip()})
            return ("copy", {"src_name": "", "dest_name": ""})

        # === 移动 ===
        elif "移动" in text:
            match = re.search(r"移动\s*(.+?)(?:到|为|至)\s*([^。，、\s]+)", text)
            if match:
                return ("move", {"src_name": match.group(1).strip(), "dest_name": match.group(2).strip()})
            return ("move", {"src_name": "", "dest_name": ""})

        # === 查看文件内容（优先于list，避免"查看文件内容"被误判为list）===
        elif re.search(r"(查看|读取|看看).*?文件", text):
            match = re.search(r"(?:查看|读取|看看).*?文件\s*([^\s。，、]+)", text)
            if match:
                return ("cat", {"name": match.group(1).strip()})
            match = re.search(r"(?:查看|读取|看看)\s*([^\s。，、]+)", text)
            name = match.group(1).strip() if match else ""
            return ("cat", {"name": name})

        # === 列出目录 ===
        elif "列出" in text or "查看目录" in text or "目录内容" in text or "显示目录" in text:
            return ("list", {"show_hidden": "隐藏" in text})

        # === 当前目录 ===
        elif "当前目录" in text or "当前路径" in text or "在哪个目录" in text:
            return ("pwd", {})

        # === 切换目录 ===
        elif re.search(r"(切换|进入|跳转)", text) and ("目录" in text or "到" in text or "进入" in text):
            # 回家目录：明确说"家目录"或"回家"
            if "回家" in text or "家目录" in text:
                return ("cd", {"name": "home"})
            # 先尝试匹配 "切换/进入 + 到 + 名称 + (可选)目录"
            match = re.search(r"(?:切换|进入|跳转)(?:到|至|去)?\s*([^\s。，、]+?)(?:目录)?$", text)
            if match:
                name = match.group(1).strip()
                if name and name not in ("到", "至", "去"):
                    return ("cd", {"name": name})
            # 匹配 "目录XXX" 或 "目录 XXX"
            match = re.search(r"目录\s*([^\s。，、]+)", text)
            if match:
                return ("cd", {"name": match.group(1).strip()})
            return ("cd", {"name": ""})

        # === 写入文件 ===
        elif re.search(r"(写入|输出|保存).*?文件", text):
            match = re.search(r"(?:写入|输出|保存)\s*(.+?)(?:到|为|至)\s*([^。，、\s]+?)(?:文件)?$", text)
            if match:
                file_name = match.group(2).strip()
                return ("echo", {"content": match.group(1).strip(), "file_name": file_name})
            return ("echo", {"content": "", "file_name": ""})

        # === 修改权限 ===
        elif "权限" in text:
            # 先匹配 "将/把 XXX (文件) 的权限" 模式
            match = re.search(r"(?:将|把|给)\s*([^\s。，、的]+?)(?:文件|的)?\s*的?\s*权限", text)
            if match:
                name = match.group(1).strip()
            else:
                # 回退：匹配 "权限 XXX"
                match = re.search(r"权限\s*([^\s。，、]+)", text)
                name = match.group(1).strip() if match else ""
            perm_match = re.search(r"(\d{3})", text)
            perm = perm_match.group(1) if perm_match else "755"
            return ("chmod", {"name": name, "perm": perm})

        # === 执行命令 ===
        elif re.search(r"(执行|运行).*?命令", text):
            match = re.search(r"(?:执行|运行).*?命令\s*(.+)", text)
            cmd = match.group(1).strip() if match else ""
            return ("run", {"command": cmd})

        return ("unknown", {})

    def _get_full_path(self, name: str) -> str:
        # 跨平台绝对路径判断
        if os.path.isabs(name):
            return name
        return os.path.join(self._current_dir, name)

    def _is_path_allowed(self, path: str) -> bool:
        real_path = os.path.realpath(path)
        for allowed in self._allowed_dirs:
            # 严格的路径前缀检查：real_path == allowed 或 real_path 以 allowed + 分隔符 开头
            if real_path == allowed:
                return True
            if real_path.startswith(allowed + os.sep):
                return True
            # Unix下也允许以 / 结尾的写法
            if allowed.endswith('/') and real_path.startswith(allowed):
                return True
        logger.warning(f"[SystemCommand] Path not allowed: {path} (real={real_path})")
        return False