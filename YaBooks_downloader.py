#!/usr/bin/env python3
"""Загрузчик книг с Яндекс.Книги"""
import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from src.config import URLS, HEADERS, TITLE_MAX_LENGTH, MYBOOKS_DIR, DOWNLOAD_RETRY_ATTEMPTS, DOWNLOAD_RETRY_DELAY
from src.auth import get_auth_token
from src.downloader import YandexBooksDownloader
from src.books import BooksDownloader
from src.audiobooks import AudiobooksDownloader
from src.comics import ComicsDownloader
from src.utils import SystemExitException

console = Console()

# Общие словари названий типов контента — раньше дублировались в нескольких
# методах YaBooksApp с одинаковым содержимым.
TYPE_NAMES_ICON = {"book": "📚 EPUB", "audiobook": "🎧 Аудиокниги", "comicbook": "🎨 Комиксы"}
CONTENT_TYPE_LABELS = {"book": "Книга", "audiobook": "Аудиокнига", "comicbook": "Комикс"}
CONTENT_TYPE_PLURAL = {"book": "книг", "audiobook": "аудиокниг", "comicbook": "комиксов"}
DOWNLOAD_TYPE_NAMES = {"audiobook": "аудиокниги", "book": "книги", "comicbook": "комикса"}
RESOURCE_TYPE_NAMES_RU = {"book": "книга", "audiobook": "аудиокнига", "comicbook": "комикс", "series": "серия", "authors": "автор"}


def pad_title(title: str) -> str:
    if len(title) > TITLE_MAX_LENGTH:
        title = title[:TITLE_MAX_LENGTH-3] + "..."
    return title.ljust(TITLE_MAX_LENGTH)


def pad_number(num: int, total: int) -> str:
    width = len(str(total))
    return f"{num:0{width}d}"


class YaBooksApp:
    def __init__(self):
        MYBOOKS_DIR.mkdir(parents=True, exist_ok=True)
        self.downloader = YandexBooksDownloader()
        self.books = BooksDownloader(self.downloader)
        self.audiobooks = AudiobooksDownloader(self.downloader)
        self.comics = ComicsDownloader(self.downloader)
        self.bitrate_set = False
        self.ffmpeg_available = self._check_ffmpeg_sync()

    @staticmethod
    def _candidate_ffmpeg_dirs() -> List[Path]:
        """Типовые папки, куда разные пакетные менеджеры Windows кладут
        ffmpeg/ffprobe, если PATH ещё не обновился в текущей сессии
        терминала (после winget install PATH применяется только к новым
        процессам, а не к уже открытому окну PowerShell)."""
        if sys.platform != "win32":
            return []

        dirs: List[Path] = []
        local_appdata = os.environ.get("LOCALAPPDATA")
        program_data = os.environ.get("PROGRAMDATA")
        user_profile = os.environ.get("USERPROFILE")

        # winget сам кладёт алиасы ffmpeg.exe/ffprobe.exe сюда
        if local_appdata:
            dirs.append(Path(local_appdata) / "Microsoft" / "WinGet" / "Links")
            # Реальные бинарники пакета Gyan.FFmpeg (архив распаковывается
            # в подпапку вида ffmpeg-X.Y-full_build/bin)
            packages_dir = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
            if packages_dir.exists():
                for pkg_dir in packages_dir.glob("Gyan.FFmpeg*"):
                    dirs.extend(pkg_dir.glob("*/bin"))
                    dirs.extend(pkg_dir.glob("bin"))

        # Chocolatey
        if program_data:
            dirs.append(Path(program_data) / "chocolatey" / "bin")

        # Scoop
        if user_profile:
            dirs.append(Path(user_profile) / "scoop" / "shims")

        return [d for d in dirs if d.exists()]

    @classmethod
    def _check_ffmpeg_sync(cls) -> bool:
        def _exists(cmd):
            try:
                subprocess.run([cmd, '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                return True
            except (FileNotFoundError, subprocess.CalledProcessError):
                return False

        if _exists('ffmpeg') and _exists('ffprobe'):
            return True

        # FFmpeg мог быть установлен только что (например, через
        # winget install ffmpeg) в текущей сессии терминала — PATH
        # процесса ещё не обновился. Ищем в типовых папках установки и,
        # если находим обе утилиты, добавляем папку в PATH этого процесса,
        # чтобы дальнейшие вызовы ffmpeg/ffprobe (в том числе из
        # audiobooks.py) находили их без перезапуска терминала.
        for directory in cls._candidate_ffmpeg_dirs():
            has_ffmpeg = (directory / "ffmpeg.exe").exists()
            has_ffprobe = (directory / "ffprobe.exe").exists()
            if has_ffmpeg and has_ffprobe:
                os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
                if _exists('ffmpeg') and _exists('ffprobe'):
                    return True

        return False

    @staticmethod
    def _print_no_ffmpeg():
        console.print("\n[red]FFmpeg не найден.[/red]")
        console.print("[yellow]Для загрузки аудиокниг необходимо установить FFmpeg.[/yellow]")
        console.print("[yellow]Скачать можно с официального сайта:[/yellow] [link]https://www.ffmpeg.org/download.html[/link]")
        console.print("[yellow]Для Windows 10/11 удобно его установить командой в PowerShell: winget install ffmpeg[/yellow]")
        console.print("[yellow]Установите FFmpeg и повторите запуск скрипта.[/yellow]")

    async def ensure_audio_ready(self) -> bool:
        """Проверяет наличие FFmpeg и (один раз за сеанс) спрашивает
        качество аудио. Возвращает False, если загрузку аудиокниг
        продолжать нельзя (нет FFmpeg или пользователь вышел из выбора)."""
        if not self.ffmpeg_available:
            self._print_no_ffmpeg()
            return False
        if not self.bitrate_set:
            try:
                self.downloader.bitrate_mode = self.audiobooks.ask_bitrate()
                self.bitrate_set = True
            except SystemExitException:
                return False
        return True

    async def initialize(self):
        token = get_auth_token()
        await self.downloader.initialize(token)

    async def close(self):
        await self.downloader.close()

    def parse_input_url(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        url = url.strip()
        if '?' in url:
            url = url.split('?')[0]
        url = url.rstrip('/')
        patterns = {
            'authors': r'books\.yandex\.ru/authors/([A-Za-z0-9_-]+)',
            'series': r'books\.yandex\.ru/series/([A-Za-z0-9_-]+)',
            'book': r'books\.yandex\.ru/books/([A-Za-z0-9_-]+)',
            'audiobook': r'books\.yandex\.ru/audiobooks/([A-Za-z0-9_-]+)',
            'comicbook': r'books\.yandex\.ru/comicbooks/([A-Za-z0-9_-]+)',
        }
        for content_type, pattern in patterns.items():
            match = re.search(pattern, url)
            if match:
                return content_type, match.group(1)
        if re.match(r'^[A-Za-z0-9_-]+$', url):
            return None, url
        return None, None

    async def determine_resource_type(self, uuid: str) -> Optional[str]:
        tests = [
            ("book", URLS["books_info"].format(uuid=uuid)),
            ("audiobook", URLS["audiobooks_info"].format(uuid=uuid)),
            ("comicbook", URLS["comicbooks_info"].format(uuid=uuid)),
            ("series", URLS["series_parts"].format(uuid=uuid)),
        ]
        for rtype, url in tests:
            try:
                info = await self.downloader.api_get(url)
                if rtype == "series" and info.get("parts") is not None:
                    return "series"
                elif info.get(rtype):
                    return rtype
            except Exception:
                continue
        return None

    async def process_single_resource(self, uuid: str, content_type: str):
        if content_type == "audiobook" and not await self.ensure_audio_ready():
            return

        info, metadata = await self.downloader.get_resource_info(uuid, content_type)
        if not self.downloader.check_availability(info, content_type):
            console.print(f"[red]Пропуск (недоступна):[/red] {metadata.get('title', 'Неизвестно')}")
            return

        resource = {
            "uuid": uuid,
            "resource_type": content_type,
            "title": metadata.get("title", ""),
            "authors": metadata.get("authors", []),
            "series_list": metadata.get("series_list", []),
        }

        series_list = metadata.get("series_list", [])
        title = metadata.get("title", "Неизвестно")
        series_info = ""
        if series_list:
            s = series_list[0]
            if s.get("title"):
                series_info = f" (серия \"{s.get('title', '')}\")"

        console.print(f"\n[cyan]Загрузка {DOWNLOAD_TYPE_NAMES.get(content_type, content_type)}: {title}{series_info}[/cyan]")

        last_exception: Optional[Exception] = None
        for attempt in range(1, DOWNLOAD_RETRY_ATTEMPTS + 1):
            last_exception = None
            try:
                if content_type == "comicbook":
                    ok = await self.comics.download(resource, verbose=True)
                elif content_type == "audiobook":
                    ok = await self.audiobooks.download(resource, metadata, verbose=True)
                else:
                    ok = await self.books.download(resource, metadata, verbose=True)
                if ok:
                    return
            except Exception as e:
                last_exception = e

            if attempt < DOWNLOAD_RETRY_ATTEMPTS:
                console.print(
                    f"[yellow]Повтор попытки {attempt + 1}/{DOWNLOAD_RETRY_ATTEMPTS}...[/yellow]"
                )
                await asyncio.sleep(DOWNLOAD_RETRY_DELAY)

        if last_exception:
            console.print(f"[red]Ошибка: {last_exception}[/red]")

    async def _download_batch(self, items: List[dict], content_type: str, plural: str) -> Tuple[int, List[str]]:
        """Скачивает список ресурсов одного типа с прогрессом.
        Возвращает (число успешных, список названий с ошибкой)."""
        label = CONTENT_TYPE_LABELS.get(content_type, "Книга")
        total = len(items)
        succeeded = 0
        failed = []

        console.print(f"\n[cyan]Скачивание {plural} ({total} шт.)...[/cyan]")
        for i, book in enumerate(items, 1):
            book_title = book.get('title', 'Неизвестно')
            console.print(f"[cyan]{label} {pad_number(i, total)}/{total}: {book_title}[/cyan]", end='')
            if content_type == "audiobook":
                console.print()

            ok = await self.download_resource(book, content_type)

            if ok:
                succeeded += 1
                if content_type != "audiobook":
                    console.print(" [green]✓[/green]")
            else:
                failed.append(book_title)
                if content_type != "audiobook":
                    console.print(" [red]✗[/red]")
        return succeeded, failed

    @staticmethod
    def _print_batch_summary(succeeded: int, total: int, failed: List[str]):
        if failed:
            console.print(f"\n[yellow]Готово: {succeeded}/{total}. Не удалось скачать:[/yellow]")
            for title in failed:
                console.print(f"  [red]✗[/red] {title}")
        else:
            console.print("[bold green]✓ Все книги скачаны[/bold green]")

    async def process_series(self, series_uuid: str):
        books = await self.downloader.get_series_books(series_uuid)
        if not books:
            console.print("[red]Книги в серии не найдены[/red]")
            return

        books_by_type = {}
        for book in books:
            rtype = book.get("resource_type")
            if not rtype:
                continue
            books_by_type.setdefault(rtype, []).append(book)
        if not books_by_type:
            console.print("[red]Не удалось определить типы книг[/red]")
            return

        console.print("\n[bold]Состав серии:[/bold]")
        for rtype, items in books_by_type.items():
            console.print(f"  {TYPE_NAMES_ICON.get(rtype, rtype)}: {len(items)} шт.")

        if len(books_by_type) == 1:
            content_type = list(books_by_type.keys())[0]
            filtered = books_by_type[content_type]
            console.print(f"\n[cyan]В серии только {TYPE_NAMES_ICON.get(content_type, content_type)}[/cyan]")
        else:
            choices = []
            display_map = {}
            for i, (rtype, items) in enumerate(books_by_type.items(), 1):
                console.print(f"{i}. {TYPE_NAMES_ICON.get(rtype, rtype)} ({len(items)} шт.)")
                display_map[str(i)] = rtype
                choices.append(str(i))
            console.print("0. Выход")
            choices.append("0")
            selected = Prompt.ask("Выберите тип", choices=choices)
            if selected == "0":
                return
            content_type = display_map[selected]
            filtered = books_by_type[content_type]

        if content_type == "audiobook" and not await self.ensure_audio_ready():
            return

        label = CONTENT_TYPE_LABELS.get(content_type, "Книга")
        plural = CONTENT_TYPE_PLURAL.get(content_type, "книг")

        table = Table(title=f"Книги серии ({len(filtered)} шт.)")
        table.add_column("№", justify="right", style="cyan")
        table.add_column("Название", style="green")
        for i, book in enumerate(filtered, 1):
            authors = book.get("authors", [])
            table.add_row(str(i), f"{book.get('series_position', '--')} - {book.get('title', 'Неизвестно')} ({authors[0] if authors else ''})")
        console.print(table)

        console.print("\n[bold]Опции:[/bold]")
        console.print("[yellow]*[/yellow] - скачать всю серию")
        console.print("[yellow]0[/yellow] - выход")
        console.print(f"Или введите номер книги (1-{len(filtered)})")
        selected = Prompt.ask("Выберите")
        if selected == "0":
            return

        if selected == "*":
            succeeded, failed = await self._download_batch(filtered, content_type, plural)
            self._print_batch_summary(succeeded, len(filtered), failed)
            return

        try:
            index = int(selected) - 1
            if 0 <= index < len(filtered):
                await self.download_resource(filtered[index], content_type)
            else:
                console.print(f"[red]Неверный номер книги[/red]")
        except ValueError:
            console.print("[red]Неверный выбор[/red]")

    async def process_author(self, author_uuid: str):
        type_config = {
            "book": ("📚 EPUB", URLS["author_books"].format(uuid=author_uuid)),
            "audiobook": ("🎧 Аудиокниги", URLS["author_audiobooks"].format(uuid=author_uuid)),
            "comicbook": ("🎨 Комиксы", URLS["author_comicbooks"].format(uuid=author_uuid)),
        }

        books_count = {}
        for rtype, (name, url) in type_config.items():
            try:
                data = await self.downloader.api_get(url)
                items = data.get("books", data.get("audiobooks", data.get("comicbooks", [])))
                count = len(items)
                books_count[rtype] = {"count": count, "type_name": name, "items": items}
            except Exception:
                books_count[rtype] = {"count": 0, "type_name": name, "items": []}

        total = sum(v["count"] for v in books_count.values())
        if total == 0:
            console.print("[red]Книги автора не найдены[/red]")
            return

        console.print(f"\n[bold]Найдено книг автора: {total}[/bold]")
        choices = []
        display_map = {}
        for i, (rtype, info) in enumerate([(k, v) for k, v in books_count.items() if v["count"] > 0], 1):
            console.print(f"{i}. {info['type_name']} ({info['count']} шт.)")
            display_map[str(i)] = (rtype, info["items"])
            choices.append(str(i))
        console.print("0. Выход")
        choices.append("0")
        selected = Prompt.ask("\n[bold]Выберите тип контента[/bold]", choices=choices)
        if selected == "0":
            return
        content_type, items = display_map[selected]

        if content_type == "audiobook" and not await self.ensure_audio_ready():
            return

        plural = CONTENT_TYPE_PLURAL.get(content_type, "книг")

        books = []
        for item in items:
            resource = item.get("book") or item.get("audiobook") or item.get("comicbook") or item
            books.append({
                "uuid": resource.get("uuid", ""),
                "title": resource.get("title", "Неизвестно"),
                "authors": self.downloader.extract_authors(resource),
                "resource_type": content_type,
            })

        succeeded, failed = await self._download_batch(books, content_type, plural)
        self._print_batch_summary(succeeded, len(books), failed)

    async def _download_once(self, resource: dict, content_type: str) -> bool:
        """Одна попытка скачивания ресурса без повторов."""
        if content_type == "book":
            return await self.books.download(resource)
        elif content_type == "audiobook":
            return await self.audiobooks.download(resource)
        elif content_type == "comicbook":
            return await self.comics.download(resource)
        else:
            console.print(f"[yellow]Неизвестный тип: {content_type}[/yellow]")
            return False

    async def download_resource(self, resource: dict, content_type: str) -> bool:
        """Скачивание ресурса с повторными попытками.

        Некоторые книги/аудиокниги/комиксы периодически отдают ошибку
        "недоступна" при пакетной загрузке, хотя при единичной попытке
        по прямой ссылке скачиваются нормально. Поэтому при неудаче
        (как при False, так и при исключении) повторяем попытку до
        DOWNLOAD_RETRY_ATTEMPTS раз с паузой DOWNLOAD_RETRY_DELAY
        секунд перед следующей попыткой.
        """
        last_exception: Optional[Exception] = None
        for attempt in range(1, DOWNLOAD_RETRY_ATTEMPTS + 1):
            last_exception = None
            try:
                if await self._download_once(resource, content_type):
                    return True
            except Exception as e:
                last_exception = e

            if attempt < DOWNLOAD_RETRY_ATTEMPTS:
                title = resource.get("title", "Неизвестно")
                console.print(
                    f"[yellow]  Повтор попытки {attempt + 1}/{DOWNLOAD_RETRY_ATTEMPTS} "
                    f"для \"{title}\"...[/yellow]"
                )
                await asyncio.sleep(DOWNLOAD_RETRY_DELAY)

        if last_exception:
            console.print(f"[red]Ошибка: {last_exception}[/red]")
        return False

    async def run(self, url: Optional[str] = None):
        args = sys.argv[1:]
        url_arg, proxy_arg = None, None
        skip_next = False

        for i, arg in enumerate(args):
            if skip_next:
                skip_next = False
                continue

            if arg == "--max_bitrate":
                self.downloader.bitrate_mode = "max_bit_rate"
                self.bitrate_set = True
            elif arg == "--min_bitrate":
                self.downloader.bitrate_mode = "min_bit_rate"
                self.bitrate_set = True
            elif arg == "--proxy":
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    proxy_arg = args[i + 1].strip()
                    skip_next = True
                else:
                    console.print("[red]Параметр --proxy требует адрес, например: --proxy http://127.0.0.1:8080[/red]")
                    return
            elif arg.startswith("--proxy="):
                proxy_arg = arg.split("=", 1)[1].strip()
                if not proxy_arg:
                    console.print("[red]Параметр --proxy требует адрес, например: --proxy=http://127.0.0.1:8080[/red]")
                    return
            elif not arg.startswith("--"):
                url_arg = arg

        if proxy_arg:
            if "://" not in proxy_arg:
                proxy_arg = f"http://{proxy_arg}"
            if not proxy_arg.startswith(("http://", "https://", "socks4://", "socks5://")):
                console.print(f"[red]Неподдерживаемый протокол прокси: {proxy_arg}[/red]")
                console.print("[yellow]Поддерживаются: http://, https://, socks4://, socks5://[/yellow]")
                return
            self.downloader.proxy = proxy_arg
            self.proxy_set = True

        if url:
            value = url
        elif url_arg:
            value = url_arg
        else:
            console.print("[bold]Использование:[/bold] python YaBooks_downloader.py [ПАРАМЕТРЫ] [ССЫЛКА]\n")
            console.print("[bold]Параметры:[/bold]")
            console.print("  --max_bitrate    Загрузка аудиокниг в максимальном качестве")
            console.print("  --min_bitrate    Загрузка аудиокниг в минимальном качестве")
            console.print("  --proxy АДРЕС    Использовать прокси (http/https/socks5)")
            console.print("\n[bold]Ссылка может быть на:[/bold]")
            console.print("  книгу        https://books.yandex.ru/books/UUID")
            if self.ffmpeg_available:
                console.print("  аудиокнигу   https://books.yandex.ru/audiobooks/UUID")
            else:
                console.print("  аудиокнигу   https://books.yandex.ru/audiobooks/UUID [red]- требуется установка FFmpeg для загрузки аудиокниг![/red]")
            console.print("  комикс       https://books.yandex.ru/comicbooks/UUID")
            console.print("  серию        https://books.yandex.ru/series/UUID")
            console.print("  автора       https://books.yandex.ru/authors/UUID")
            console.print("\n[bold]Примеры:[/bold]")
            console.print("  python YaBooks_downloader.py AbCd1234")
            console.print("  python YaBooks_downloader.py --min_bitrate https://books.yandex.ru/audiobooks/AbCd1234")
            console.print("  python YaBooks_downloader.py --proxy http://127.0.0.1:8080 https://books.yandex.ru/books/AbCd1234")
            console.print("  python YaBooks_downloader.py (интерактивный режим)\n")
            value = input("> ").strip()
            if not value:
                return

        content_type, uuid = self.parse_input_url(value)
        if not uuid:
            console.print("[red]Не удалось распознать ссылку или UUID[/red]")
            return
        if not content_type:
            content_type = await self.determine_resource_type(uuid)
            if not content_type:
                console.print("[red]Не удалось определить тип ресурса[/red]")
                return

        # Для одиночной аудиокниги проверка FFmpeg/битрейта повторно
        # выполняется внутри process_single_resource (ensure_audio_ready);
        # для series/authors тип контента станет известен только после
        # запроса состава, поэтому там она вызывается на месте.

        type_name_ru = RESOURCE_TYPE_NAMES_RU.get(content_type, content_type)
        console.print(f"[cyan]Определён тип: {type_name_ru}[/cyan]")
        if self.bitrate_set:
            name = "максимальное" if self.downloader.bitrate_mode == "max_bit_rate" else "минимальное"
            console.print(f"[cyan]Качество аудио: {name}[/cyan]")
        if self.proxy_set:
            console.print(f"[cyan]Прокси: {self.downloader.proxy}[/cyan]")

        try:
            if content_type == "authors":
                await self.process_author(uuid)
            elif content_type == "series":
                await self.process_series(uuid)
            elif content_type in ("book", "audiobook", "comicbook"):
                await self.process_single_resource(uuid, content_type)
            else:
                console.print(f"[red]Неподдерживаемый тип: {content_type}[/red]")
        except SystemExitException:
            console.print("[yellow]Выход...[/yellow]")

async def main():
    app = YaBooksApp()
    await app.initialize()
    try:
        await app.run()
    finally:
        await app.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Остановлено пользователем[/yellow]")
    except SystemExitException:
        console.print("[yellow]Выход...[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Критическая ошибка: {e}[/red]")
