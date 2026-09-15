from __future__ import annotations
import os
import json
import random
from typing import Dict, Any, List, Optional
from ..utils import logger, get_project_root


TOOLS_DESCRIPTIONS: List[Dict[str, Any]] = []


def register_tool(description: Dict[str, Any]) -> None:
    TOOLS_DESCRIPTIONS.append(description)


def get_tools_descriptions() -> List[Dict[str, Any]]:
    return TOOLS_DESCRIPTIONS


def create_folder(folder_name: str, path: str = None) -> str:
    if path is None:
        path = os.path.join(get_project_root(), "data")
    full_path = os.path.join(path, folder_name)
    try:
        os.makedirs(full_path, exist_ok=True)
        return f"成功创建文件夹：{full_path}"
    except Exception as e:
        return f"创建失败：{str(e)}"


register_tool({
    "name": "create_folder",
    "description": "当用户要求创建文件夹或目录时调用此工具",
    "parameters": {
        "type": "object",
        "properties": {
            "folder_name": {"type": "string", "description": "要创建的文件夹名称，例如'我的音乐'"},
            "path": {"type": "string", "description": "要创建文件夹的父目录路径，默认是项目的data目录"},
        },
        "required": ["folder_name"],
    },
})


def list_directory(path: str = None) -> str:
    if path is None:
        path = get_project_root()
    try:
        entries = os.listdir(path)
        files = [f for f in entries if os.path.isfile(os.path.join(path, f))]
        folders = [f for f in entries if os.path.isdir(os.path.join(path, f))]
        result = f"目录 {path} 包含:\n"
        if folders:
            result += f"文件夹: {', '.join(folders)}\n"
        if files:
            result += f"文件: {', '.join(files)}"
        return result
    except Exception as e:
        return f"读取目录失败：{str(e)}"


register_tool({
    "name": "list_directory",
    "description": "列出指定目录下的文件和文件夹",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要列出的目录路径，默认是项目根目录"},
        },
        "required": [],
    },
})


def delete_file(file_path: str) -> str:
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return f"成功删除文件：{file_path}"
        else:
            return f"文件不存在：{file_path}"
    except Exception as e:
        return f"删除失败：{str(e)}"


register_tool({
    "name": "delete_file",
    "description": "删除指定的文件",
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "要删除的文件完整路径"},
        },
        "required": ["file_path"],
    },
})


def write_file(file_path: str, content: str) -> str:
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"成功写入文件：{file_path}"
    except Exception as e:
        return f"写入失败：{str(e)}"


register_tool({
    "name": "write_file",
    "description": "向指定文件写入内容，会覆盖原有内容",
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "要写入的文件完整路径"},
            "content": {"type": "string", "description": "要写入的内容"},
        },
        "required": ["file_path", "content"],
    },
})


def get_system_info() -> str:
    try:
        import platform
        info = f"系统信息:\n"
        info += f"操作系统: {platform.system()} {platform.release()}\n"
        info += f"Python版本: {platform.python_version()}\n"
        info += f"CPU: {platform.processor()}"
        return info
    except Exception as e:
        return f"获取系统信息失败：{str(e)}"


register_tool({
    "name": "get_system_info",
    "description": "获取当前系统的基本信息",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
})


_TOOL_FUNCTIONS: Dict[str, callable] = {
    "create_folder": create_folder,
    "list_directory": list_directory,
    "delete_file": delete_file,
    "write_file": write_file,
    "get_system_info": get_system_info,
}


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    if tool_name not in _TOOL_FUNCTIONS:
        return f"未知工具：{tool_name}"
    
    try:
        func = _TOOL_FUNCTIONS[tool_name]
        result = func(**arguments)
        return str(result)
    except Exception as e:
        return f"工具执行失败：{str(e)}"


def get_available_tools() -> List[str]:
    return list(_TOOL_FUNCTIONS.keys())