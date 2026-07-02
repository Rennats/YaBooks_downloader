"""Базовый класс загрузчика"""
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import aiofiles
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from rich.console import Console

from src.config import HEADERS, URLS, MYBOOKS_DIR, MAX_CONCURRENT_DOWNLOADS
from src.utils import sanitize_filename

console = Console()


class YandexBooksDownloader:
    """Базовый класс для загрузки книг"""
    
    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self.download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        self.bitrate_mode = "max_bit_rate"

    async def initialize(self, token: str):
        HEADERS["auth-token"] = token
        self.client = httpx.AsyncClient(
            headers=HEADERS,
            timeout=httpx.Timeout(120.0),
            follow_redirects=True,
            http2=True,
            verify=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def close(self):
        if self.client:
            await self.client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def api_get(self, url: str) -> dict:
        response = await self.client.get(url)
        if response.status_code == 401:
            console.print("\n[yellow]Токен истёк, требуется повторная авторизация[/yellow]")
            from src.auth import get_auth_token
            token_file = Path("token.txt")
            if token_file.exists():
                token_file.unlink()
            new_token = get_auth_token()
            if new_token:
                HEADERS["auth-token"] = new_token
                self.client.headers["auth-token"] = new_token
                response = await self.client.get(url)
        if response.status_code == 429:
            raise Exception("Слишком много запросов")
        response.raise_for_status()
        return response.json()

    async def download_file(self, url: str, filepath: Path):
        """Скачать файл на диск"""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        if filepath.exists() and filepath.stat().st_size > 0:
            return

        temp_path = filepath.with_suffix(filepath.suffix + ".part")
        try:
            async with self.client.stream("GET", url) as response:
                response.raise_for_status()
                async with aiofiles.open(temp_path, "wb") as f:
                    async for chunk in response.aiter_bytes(1024 * 512):
                        await f.write(chunk)
            temp_path.replace(filepath)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise e

    async def download_file_sequential(self, url: str, filepath: Path, chunk_size: int = 10 * 1024 * 1024):
        """Скачать файл последовательно"""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        if filepath.exists() and filepath.stat().st_size > 0:
            return

        temp_path = filepath.with_suffix(filepath.suffix + ".part")
        try:
            async with self.client.stream("GET", url) as response:
                response.raise_for_status()
                async with aiofiles.open(temp_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size):
                        await f.write(chunk)
            temp_path.replace(filepath)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise e

    async def download_file_content(self, url: str) -> bytes:
        """Скачать файл в память"""
        response = await self.client.get(url)
        response.raise_for_status()
        return response.content

    def build_book_path(self, author_name: str, title: str, series_name: Optional[str] = None, series_position: Optional[str] = None) -> Path:
        """Построение пути для сохранения книги"""
        author_name = self.format_author_name(author_name)  # Форматируем только для папки
        author_name = sanitize_filename(author_name)
        title = sanitize_filename(title)

        if series_name:
            series_name = sanitize_filename(series_name)
            base = MYBOOKS_DIR / author_name / series_name
            filename = f"{series_position} - {title}" if series_position else title
        else:
            base = MYBOOKS_DIR / author_name
            filename = title

        return base / filename

    def check_availability(self, info: dict, content_type: str) -> bool:
        """Проверка доступности ресурса"""
        resource = info.get(content_type, info)
        can_be_read = resource.get("can_be_read", True)
        return can_be_read != False

    @staticmethod
    def format_author_name(name: str) -> str:
        """Форматирует имя автора в формат 'Фамилия Имя'"""
        parts = name.strip().split()
        if len(parts) == 2:
            return f"{parts[1]} {parts[0]}"
        elif len(parts) == 3:
            return f"{parts[2]} {parts[0]} {parts[1]}"
        return name

    def extract_authors(self, data: dict) -> List[str]:
        """Извлечение авторов из данных API"""
        authors = []
        for author_obj in data.get("authors_objects", []):
            if isinstance(author_obj, dict):
                name = author_obj.get("name") or author_obj.get("title", "")
                if name and name not in authors:
                    authors.append(name)

        authors_field = data.get("authors", [])
        if isinstance(authors_field, str) and authors_field:
            for author in authors_field.split(","):
                author = author.strip()
                if author and author not in authors:
                    authors.append(author)
        elif isinstance(authors_field, list):
            for author in authors_field:
                name = author.get("name") if isinstance(author, dict) else author
                if name and name not in authors:
                    authors.append(name)

        return authors

    async def get_resource_info(self, uuid: str, content_type: str) -> Tuple[dict, dict]:
        """Получение полной информации о ресурсе"""
        urls = {
            "book": URLS["books_info"].format(uuid=uuid),
            "audiobook": URLS["audiobooks_info"].format(uuid=uuid),
            "comicbook": URLS["comicbooks_info"].format(uuid=uuid),
        }
        url = urls.get(content_type)
        if not url:
            raise ValueError(f"Неизвестный тип содержимого: {content_type}")
        
        info = await self.api_get(url)
        metadata = self.extract_metadata(info, content_type)
        return info, metadata

    def extract_metadata(self, data: dict, content_type: str = "book") -> dict:
        """Извлечение метаданных"""
        book_data = data.get(content_type, data)

        uuid = book_data.get("uuid", "")
        title = book_data.get("title", "Неизвестно")
        authors = self.extract_authors(data) or self.extract_authors(book_data)
        annotation = book_data.get("annotation", "")

        # Жанры
        topics = book_data.get("topics", [])
        genres = []
        if isinstance(topics, list):
            for topic in topics:
                if isinstance(topic, dict):
                    name = topic.get("title") or topic.get("name") or ""
                    if name and name != "Виртуальный рассказчик":
                        genres.append(name)
                elif isinstance(topic, str) and topic != "Виртуальный рассказчик":
                    genres.append(topic)

        # Издатели
        publishers_data = book_data.get("publishers", [])
        publishers = []
        if isinstance(publishers_data, list):
            for publisher in publishers_data:
                if isinstance(publisher, dict):
                    name = publisher.get("title") or publisher.get("name") or ""
                    if name:
                        publishers.append(name)
                elif isinstance(publisher, str):
                    publishers.append(publisher)

        # Серии
        series_data = book_data.get("series_list") or data.get("series_list", [])
        series_list = []
        if isinstance(series_data, list):
            for series in series_data:
                if isinstance(series, dict):
                    series_info = {
                        "title": series.get("title", ""),
                        "position_label": series.get("position_label") or series.get("position", ""),
                        "uuid": series.get("uuid", ""),
                    }
                    series_list.append(series_info)

        # Обложка
        cover_data = data.get("cover") or book_data.get("cover", {})
        cover_url = None
        if isinstance(cover_data, dict):
            cover_url = cover_data.get("large") or cover_data.get("medium") or cover_data.get("small")

        # Остальные поля
        original_year = book_data.get("original_year")
        owner_catalog_title = book_data.get("owner_catalog_title")

        # Источник
        type_url_map = {"book": "books", "audiobook": "audiobooks", "comicbook": "comicbooks"}
        url_type = type_url_map.get(content_type, "books")
        source = f"https://books.yandex.ru/{url_type}/{uuid}"

        metadata = {
            "title": title,
            "authors": authors,
            "annotation": annotation,
            "genres": genres,
            "publishers": publishers,
            "series_list": series_list,
            "cover_url": cover_url,
            "uuid": uuid,
            "content_type": content_type,
            "source": source,
            "original_year": original_year,
            "owner_catalog_title": owner_catalog_title,
        }

        return metadata

    async def get_series_books(self, series_uuid: str) -> List[dict]:
        """Получение списка книг серии"""
        url = URLS["series_parts"].format(uuid=series_uuid)
        data = await self.api_get(url)
        
        books = []
        for part in data.get("parts", []):
            resource = part.get("resource") or part.get("book") or part.get("audiobook") or part.get("comicbook")
            if not resource:
                continue
            
            position = part.get("position_label") or part.get("position") or 0
            try:
                series_position = f"{int(float(position)):02d}"
            except:
                series_position = str(position)
            
            books.append({
                "uuid": resource.get("uuid", ""),
                "title": resource.get("title", "Неизвестно"),
                "authors": self.extract_authors(resource),
                "resource_type": part.get("resource_type", "book"),
                "series_position": series_position,
            })
        
        return books