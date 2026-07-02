"""Загрузка комиксов"""
from pathlib import Path
from rich.console import Console

from src.config import URLS
from src.downloader import YandexBooksDownloader

console = Console()


class ComicsDownloader:
    """Загрузчик комиксов"""
    
    def __init__(self, downloader: YandexBooksDownloader):
        self.downloader = downloader

    async def download(self, resource: dict, verbose: bool = False):
        """Скачивание комикса в формате CBZ"""
        uuid = resource["uuid"]
        
        meta_url = URLS["comicbook_meta"].format(uuid=uuid)
        try:
            meta_data = await self.downloader.api_get(meta_url)
        except Exception as e:
            if verbose:
                console.print(f"[red]Пропуск (недоступна):[/red] {resource.get('title', 'Неизвестно')}")
            else:
                console.print(f"[red]   ✗   (недоступна)[/red]")
            return
        
        uris = meta_data.get("uris", {})
        download_url = uris.get("zip")
        if not download_url:
            if verbose:
                console.print(f"[red]Пропуск (недоступна):[/red] {resource.get('title', 'Неизвестно')}")
            else:
                console.print(f"[red]   ✗   (недоступна)[/red]")
            return
        
        metadata = None
        try:
            info, metadata = await self.downloader.get_resource_info(uuid, "comicbook")
        except:
            pass
        
        title = resource.get("title", "Неизвестное название")
        authors = resource.get("authors", [])
        author = authors[0] if authors else "Неизвестный автор"
        
        series_name = None
        series_position = None
        
        if metadata and metadata.get("series_list"):
            first_series = metadata["series_list"][0]
            series_name = first_series.get("title")
            position = first_series.get("position_label", "1")
            try:
                pos_num = int(float(position))
                if pos_num >= 100:
                    series_position = f"{pos_num:03d}"
                else:
                    series_position = f"{pos_num:02d}"
            except:
                series_position = str(position)
        
        path = self.downloader.build_book_path(author, title, series_name, series_position)
        
        cbz_path = Path(str(path) + ".cbz")
        path.parent.mkdir(parents=True, exist_ok=True)
        
        temp_path = path.parent / "temp_comicbook.cbz"
        await self.downloader.download_file(download_url, temp_path)
        
        if temp_path.exists():
            if temp_path != cbz_path:
                if cbz_path.exists():
                    cbz_path.unlink()
                temp_path.rename(cbz_path)
        
        if cbz_path.exists():
            file_size = cbz_path.stat().st_size
            if verbose:
                console.print(f"[green]Комикс загружен   ✓   ({file_size / 1024 / 1024:.1f} МБ)[/green]")
        else:
            console.print("\n[red]Не удалось скачать комикс[/red]")