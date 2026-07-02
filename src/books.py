"""Загрузка EPUB книг"""
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from ebooklib import epub
from rich.console import Console

from src.config import URLS
from src.downloader import YandexBooksDownloader

console = Console()


class BooksDownloader:
    """Загрузчик EPUB книг"""
    
    def __init__(self, downloader: YandexBooksDownloader):
        self.downloader = downloader

    async def download(self, resource: dict, metadata: Optional[dict] = None, verbose: bool = False):
        """Скачивание EPUB книги"""
        uuid = resource["uuid"]
        
        info = None
        if not metadata:
            if verbose:
                console.print("[dim]Получение сведений о книге...[/dim]")
            info, metadata = await self.downloader.get_resource_info(uuid, "book")
        else:
            try:
                info, _ = await self.downloader.get_resource_info(uuid, "book")
            except:
                pass
        
        if info and not self.downloader.check_availability(info, "book"):
            title = metadata.get('title', 'Unknown') if metadata else resource.get('title', 'Unknown')
            if verbose:
                console.print(f"[red]Пропуск (недоступна):[/red] {title}")
            else:
                console.print(f"[red]   ✗   (недоступна)[/red]")
            return
        
        title = metadata.get("title", "Неизвестное название")
        author = metadata.get("authors", ["Неизвестный автор"])[0] if metadata.get("authors") else "Неизвестный автор"

        series_name = None
        series_position = None
        
        if metadata.get("series_list"):
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
        path.parent.mkdir(parents=True, exist_ok=True)
        
        temp_path = path.parent / "temp_ebook.epub"
        
        content_url = URLS["book_content"].format(uuid=uuid)
        if verbose:
            console.print("[dim]Скачивание книги...[/dim]")
        await self.downloader.download_file(content_url, temp_path)
        
        if not temp_path.exists():
            console.print("[red]Ошибка скачивания книги[/red]")
            return
        
        cover_url = metadata.get("cover_url")
        if not cover_url:
            cover_url = resource.get("cover", {}).get("large")
        
        cover_data = None
        if cover_url:
            try:
                if verbose:
                    console.print("[dim]Скачивание обложки...[/dim]")
                import httpx
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    response = await client.get(cover_url)
                    response.raise_for_status()
                    cover_data = response.content
            except Exception as e:
                if verbose:
                    console.print(f"[dim]Не удалось скачать обложку: {e}[/dim]")
        
        if cover_data:
            if verbose:
                console.print("[dim]Замена обложки...[/dim]")
            self.replace_cover(temp_path, cover_data)
        
        if verbose:
            console.print("[dim]Обновление метаданных...[/dim]")
        self.update_metadata(temp_path, metadata, info)
        
        epub_path = Path(str(path) + ".epub")
        if epub_path.exists():
            epub_path.unlink()
        temp_path.rename(epub_path)
        
        if verbose:
            console.print(f"[green]Книга загружена!   ✓[/green]")

    def _remove_missing_images_from_manifest(self, epub_path: Path):
        """Удаляет из content.opf ссылки на отсутствующие в архиве изображения"""
        import shutil
        with zipfile.ZipFile(str(epub_path), 'r') as zf:
            real_files = set(zf.namelist())
            # Найти OPF файл
            opf_name = None
            for name in real_files:
                if name.endswith('.opf'):
                    opf_name = name
                    break
            if not opf_name:
                return

            opf_content = zf.read(opf_name)
            root = ET.fromstring(opf_content)
            ns = {'opf': 'http://www.idpf.org/2007/opf'}
            manifest = root.find('.//opf:manifest', ns)
            if manifest is None:
                return

            opf_dir = os.path.dirname(opf_name)
            items_to_remove = []
            for item in manifest.findall('opf:item', ns):
                href = item.get('href')
                full_path = os.path.normpath(os.path.join(opf_dir, href)).replace('\\', '/')
                if full_path not in real_files:
                    items_to_remove.append(item)
            if not items_to_remove:
                return  # всё в порядке

            # Удаляем элементы
            for item in items_to_remove:
                manifest.remove(item)

            # Сохраняем изменённый OPF во временный архив
            modified_opf = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            tmp_fd, tmp_epub = tempfile.mkstemp(suffix='.epub')
            os.close(tmp_fd)
            with zipfile.ZipFile(str(epub_path), 'r') as zin:
                with zipfile.ZipFile(tmp_epub, 'w') as zout:
                    for entry in zin.infolist():
                        data = zin.read(entry.filename)
                        if entry.filename == opf_name:
                            zout.writestr(entry, modified_opf)
                        else:
                            zout.writestr(entry, data)
            shutil.move(tmp_epub, str(epub_path))

    def update_metadata(self, epub_path: Path, metadata: dict, book_info: dict = None):
        """Обновление метаданных EPUB файла — создаём новую книгу с чистыми метаданными"""
        try:
            if not epub_path.exists():
                return

            # Предварительно исправляем content.opf, удаляя ссылки на отсутствующие файлы
            self._remove_missing_images_from_manifest(epub_path)

            original = epub.read_epub(str(epub_path))
            new_book = epub.EpubBook()

            new_book.spine = original.spine
            new_book.toc = original.toc
            new_book.guide = original.guide
            new_book.items = original.items
            if hasattr(original, 'cover') and original.cover:
                new_book.cover = original.cover

            if metadata.get("title"):
                new_book.set_title(metadata["title"])

            authors = metadata.get("authors", [])
            if authors:
                new_book.add_author(authors[0])
                for author in authors[1:]:
                    new_book.add_metadata("DC", "contributor", author)

            if metadata.get("annotation"):
                new_book.add_metadata("DC", "description", metadata["annotation"])

            for publisher in metadata.get("publishers", []):
                new_book.add_metadata("DC", "publisher", publisher)

            for genre in metadata.get("genres", []):
                if genre != "Виртуальный рассказчик":
                    new_book.add_metadata("DC", "subject", genre)

            for series in metadata.get("series_list", []):
                if series.get("title"):
                    series_info = f"Серия: {series['title']}"
                    if series.get("position_label"):
                        series_info += f", Номер: {series['position_label']}"
                    new_book.add_metadata("DC", "relation", series_info)

            if metadata.get("source"):
                new_book.add_metadata("DC", "source", metadata["source"])

            if metadata.get("original_year"):
                new_book.add_metadata("DC", "date", str(metadata["original_year"]))

            if metadata.get("owner_catalog_title"):
                new_book.add_metadata("DC", "rights", metadata["owner_catalog_title"])

            has_cover_image = any(
                (isinstance(item, epub.EpubItem) and item.file_name == 'cover.jpg')
                for item in new_book.items
            )
            if has_cover_image:
                found_meta = False
                for item in new_book.metadata:
                    if isinstance(item, tuple) and len(item) >= 2 and item[1] == 'meta':
                        attrs = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
                        if attrs.get('name') == 'cover':
                            found_meta = True
                            break
                if not found_meta:
                    new_book.add_metadata(None, 'meta', '', {'name': 'cover', 'content': 'cover_image'})

            epub.write_epub(str(epub_path), new_book)

        except Exception as e:
            console.print(f"\n[red]Ошибка обновления метаданных:[/red] {e}")

    def replace_cover(self, epub_path: Path, cover_data: bytes):
        """Замена или добавление обложки в EPUB файле"""
        import shutil
        try:
            if not epub_path.exists():
                console.print("\n[red]EPUB файл не найден[/red]")
                return

            if not cover_data or len(cover_data) < 100:
                console.print("\n[yellow]Обложка слишком маленькая, пропуск[/yellow]")
                return

            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".epub")
            os.close(tmp_fd)

            cover_replaced = False
            with zipfile.ZipFile(epub_path, "r") as zin:
                with zipfile.ZipFile(tmp_path, "w") as zout:
                    for item in zin.infolist():
                        data = zin.read(item.filename)
                        if (item.filename.lower().endswith("cover.jpg") or 
                            item.filename.lower().endswith("cover.jpeg") or
                            item.filename.lower().endswith("cover.png")):
                            data = cover_data
                            cover_replaced = True
                        if item.filename == "mimetype":
                            zout.writestr(item, data, compress_type=zipfile.ZIP_STORED)
                        else:
                            zout.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED)

            if cover_replaced:
                shutil.move(tmp_path, epub_path)
                return
            
            os.unlink(tmp_path)
            
            try:
                book = epub.read_epub(str(epub_path))
                book.set_cover("cover.jpg", cover_data)
                epub.write_epub(str(epub_path), book)
                return
            except:
                pass
            
            self._add_cover_manually(epub_path, cover_data)
            
        except Exception as e:
            console.print(f"\n[red]Ошибка замены обложки:[/red] {e}")
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _add_cover_manually(self, epub_path: Path, cover_data: bytes):
        """Ручное добавление обложки в EPUB"""
        import shutil
        import xml.etree.ElementTree as ET
        
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".epub")
        os.close(tmp_fd)
        
        try:
            with zipfile.ZipFile(epub_path, "r") as zin:
                with zipfile.ZipFile(tmp_path, "w") as zout:
                    for item in zin.infolist():
                        data = zin.read(item.filename)
                        
                        if item.filename.lower().endswith("content.opf"):
                            try:
                                root = ET.fromstring(data)
                                ns = {'opf': 'http://www.idpf.org/2007/opf'}
                                ET.register_namespace('', 'http://www.idpf.org/2007/opf')
                                
                                manifest = root.find('.//opf:manifest', ns)
                                if manifest is not None:
                                    has_cover = any(
                                        item_elem.get('id') == 'cover' or 
                                        item_elem.get('properties') == 'cover-image'
                                        for item_elem in manifest.findall('opf:item', ns)
                                    )
                                    
                                    if not has_cover:
                                        cover_item = ET.SubElement(manifest, '{http://www.idpf.org/2007/opf}item')
                                        cover_item.set('id', 'cover')
                                        cover_item.set('href', 'cover.jpg')
                                        cover_item.set('media-type', 'image/jpeg')
                                        cover_item.set('properties', 'cover-image')
                                        
                                        metadata_elem = root.find('.//opf:metadata', ns)
                                        if metadata_elem is not None:
                                            meta = ET.SubElement(metadata_elem, '{http://www.idpf.org/2007/opf}meta')
                                            meta.set('name', 'cover')
                                            meta.set('content', 'cover_image')
                                        
                                        guide = root.find('.//opf:guide', ns)
                                        if guide is None:
                                            guide = ET.SubElement(root, '{http://www.idpf.org/2007/opf}guide')
                                        reference = ET.SubElement(guide, '{http://www.idpf.org/2007/opf}reference')
                                        reference.set('type', 'cover')
                                        reference.set('title', 'Cover')
                                        reference.set('href', 'cover.jpg')
                                        
                                        data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                            except:
                                pass
                        
                        if item.filename == "mimetype":
                            zout.writestr(item, data, compress_type=zipfile.ZIP_STORED)
                        else:
                            zout.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED)
                    
                    cover_info = zipfile.ZipInfo("OEBPS/cover.jpg")
                    zout.writestr(cover_info, cover_data, compress_type=zipfile.ZIP_DEFLATED)
            
            shutil.move(tmp_path, epub_path)
        except:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)