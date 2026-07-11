"""Утилиты"""
import re
from pathlib import Path

class SystemExitException(Exception):
    """Исключение для выхода из программы"""
    pass


def sanitize_filename(name: str) -> str:
    """Очистка имени файла от недопустимых символов с безопасной заменой"""
    if not name:
        return "Unknown"
    replacements = {
        '\\': '-',
        '/': '-',
        ':': ';',
        '*': 'x',
        '?': '!',
        '"': "'",
        '<': '(',
        '>': ')',
        '|': '-',
    }
    for forbidden, replacement in replacements.items():
        name = name.replace(forbidden, replacement)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()