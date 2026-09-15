import os
from .logger import logger


def get_project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


__all__ = ["logger", "get_project_root"]
