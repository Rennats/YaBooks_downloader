"""Утилиты"""
import re
import sys
from pathlib import Path

class SystemExitException(Exception):
    """Исключение для выхода из программы"""
    pass


def sanitize_filename(name: str) -> str:
    """Очистка имени файла от недопустимых символов"""
    if not name:
        return "Unknown"
    name = re.sub(r'[\\/:*?"<>|]', ' ', str(name))
    name = re.sub(r'\s+', ' ', name)
    return name.strip()