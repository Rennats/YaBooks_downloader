"""Авторизация"""
from pathlib import Path
from typing import Optional
from rich.console import Console

from src.config import HEADERS, BASE_URL

console = Console()


def get_auth_token() -> str:
    """Получение токена авторизации"""
    token_file = Path("token.txt")
    
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    
    if HEADERS.get('auth-token'):
        return HEADERS['auth-token']
    
    console.print("[yellow]Токен не найден. Необходима авторизация...[/yellow]")
    auth_token = run_auth_webview()
    
    if auth_token:
        token_file.write_text(auth_token, encoding="utf-8")
        console.print("[green]Токен сохранен в token.txt[/green]")
    else:
        console.print("[red]Не удалось получить токен автоматически[/red]")
        console.print("[yellow]Введите auth-token вручную:[/yellow]")
        auth_token = input("> ").strip()
        if auth_token:
            token_file.write_text(auth_token, encoding="utf-8")
    
    return auth_token


def run_auth_webview() -> Optional[str]:
    """Запуск окна авторизации для получения токена"""
    try:
        import urllib.parse
        import webview

        def on_loaded(window):
            if "yx4483e97bab6e486a9822973109a14d05.oauth.yandex.ru" in urllib.parse.urlparse(window.get_current_url()).netloc:
                url = urllib.parse.urlparse(window.get_current_url())
                try:
                    window.auth_token = urllib.parse.parse_qs(url.fragment)['access_token'][0]
                    window.destroy()
                except:
                    pass

        window = webview.create_window(
            'Вход в аккаунт для получения токена',
            'https://oauth.yandex.ru/authorize?response_type=token&client_id=4483e97bab6e486a9822973109a14d05'
        )
        window.events.loaded += on_loaded
        window.auth_token = None
        webview.start()
        return window.auth_token
    except ImportError:
        console.print("[yellow]pywebview не установлен. Установите: pip install pywebview[/yellow]")
        return None
    except Exception as e:
        console.print(f"[red]Ошибка окна авторизации: {e}[/red]")
        return None