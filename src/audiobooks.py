"""Загрузка аудиокниг"""
import asyncio
import re
import shutil
import subprocess
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional, List

import aiofiles
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image
from rich.console import Console

from src.config import URLS
from src.downloader import YandexBooksDownloader
from src.utils import SystemExitException

console = Console()


class AudiobooksDownloader:
    """Загрузчик аудиокниг"""
    
    def __init__(self, downloader: YandexBooksDownloader):
        self.downloader = downloader

    def ask_bitrate(self) -> str:
        """Запрос выбора битрейта"""
        try:
            console.print("\n[bold]Выберите качество аудио:[/bold]")
            console.print("1. Максимальное (по умолчанию)")
            console.print("2. Минимальное (быстрее, меньше размер)")
            console.print("0. Выход")
            
            choice = console.input("[bold]Выберите качество [1/2/0/] (1): [/bold]").strip()
            
            if choice == "0":
                raise SystemExitException()
            elif choice == "2":
                return "min_bit_rate"
            return "max_bit_rate"
        except SystemExitException:
            raise
        except:
            return "max_bit_rate"

    async def download(self, resource: dict, metadata: Optional[dict] = None, verbose: bool = False):
        """Скачивание аудиокниги по главам"""
        uuid = resource["uuid"]
        
        if not metadata:
            info, metadata = await self.downloader.get_resource_info(uuid, "audiobook")
            if info and not self.downloader.check_availability(info, "audiobook"):
                title = metadata.get('title', 'Неизвестно')
                if verbose:
                    console.print(f"[red]Пропуск (недоступна):[/red] {title}")
                else:
                    console.print(f"[red]   ✗   (недоступна)[/red]")
                return
        
        if metadata.get("series_list"):
            series_uuid = metadata["series_list"][0].get("uuid")
            if series_uuid:
                try:
                    series_books = await self.downloader.get_series_books(series_uuid)
                    for series in metadata["series_list"]:
                        if series.get("uuid") == series_uuid:
                            series["total_parts"] = len(series_books)
                            for i, book in enumerate(series_books, start=1):
                                if book.get("uuid") == uuid:
                                    series["position_label"] = str(i)
                                    break
                except:
                    pass
        
        playlist_url = URLS["audiobook_playlist"].format(uuid=uuid)
        try:
            playlist_data = await self.downloader.api_get(playlist_url)
        except Exception as e:
            console.print(f"\n[red]Ошибка получения плейлиста:[/red] {e}")
            return
        
        tracks = playlist_data.get("tracks", [])
        if not tracks:
            console.print("\n[red]Треки не найдены[/red]")
            return
        
        tracks.sort(key=lambda x: x.get("number", 0))
        
        chapters_info = []
        for track in tracks:
            offline = track.get("offline", {})
            bitrate_data = offline.get(self.downloader.bitrate_mode, {})
            url = bitrate_data.get("url")
            
            if not url:
                alt_mode = "min_bit_rate" if self.downloader.bitrate_mode == "max_bit_rate" else "max_bit_rate"
                bitrate_data = offline.get(alt_mode, {})
                url = bitrate_data.get("url")
            
            if url:
                url = url.replace(".m3u8", ".m4a")
                chapter_number = track.get("number", len(chapters_info) + 1)
                chapter_title = track.get("title", f"Глава {chapter_number:02d}")
                
                duration_info = track.get("duration", {})
                chapters_info.append({
                    "url": url,
                    "number": chapter_number,
                    "title": chapter_title,
                    "offset": duration_info.get("offset", 0),
                    "duration": duration_info.get("seconds", 0),
                })
        
        if not chapters_info:
            console.print("\n[red]Не найдены ссылки для скачивания аудио[/red]")
            return
        
        title = resource.get("title", "Неизвестное название")
        authors = resource.get("authors", [])
        author = authors[0] if authors else "Неизвестный автор"
        
        series_name = None
        series_position = None
        
        if metadata.get("series_list") and isinstance(metadata["series_list"][0], dict):
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
        
        m4b_path = Path(str(path) + ".m4b")
        
        cover_url = metadata.get("cover_url")
        if not cover_url:
            cover_url = resource.get("cover", {}).get("large")
        
        cover_data = None
        if cover_url:
            try:
                cover_data = await self.downloader.download_file_content(cover_url)
            except:
                pass
        
        temp_dir = path.parent / f"temp_{uuid}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        audio_files = []
        console.print(f"   [cyan]Скачивание глав ({len(chapters_info)} шт.)...[/cyan]")
        for idx, chapter in enumerate(chapters_info):
            chapter_num = chapter["number"]
            chapter_file = temp_dir / f"Глава_{chapter_num:02d}.m4a"
            try:
                await self.downloader.download_file_sequential(chapter["url"], chapter_file)
                if chapter_file.exists() and chapter_file.stat().st_size > 0:
                    audio_files.append(chapter_file)
            except Exception as e:
                console.print(f"\n   [yellow]Ошибка скачивания {chapter['title']}:[/yellow] {e}")
        
        if not audio_files:
            console.print("\n   [red]Не удалось скачать ни одной главы[/red]")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        
        console.print("   [cyan]Объединение глав в M4B...[/cyan]")
        success = await self.merge_chapters(audio_files, chapters_info, m4b_path, cover_data, metadata)
        
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        if success and m4b_path.exists():
            file_size = m4b_path.stat().st_size
            console.print(f"[green]Аудиокнига загружена   ✓   ({file_size / 1024 / 1024:.1f} МБ)[/green]")
        else:
            console.print("\n   [red]Не удалось создать M4B файл[/red]")

    async def merge_chapters(
        self, 
        audio_files: List[Path], 
        chapters_info: List[dict],
        output_path: Path, 
        cover_data: Optional[bytes], 
        metadata: dict
    ) -> bool:
        """Объединение глав в M4B с метаданными"""
        temp_dir = output_path.parent / "merge_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        filelist_path = temp_dir / "chapters_list.txt"
        chapters_metadata_path = temp_dir / "chapters_metadata.txt"
        cover_path = temp_dir / "cover.jpg"
        temp_output = temp_dir / "output.m4b"
        
        try:
            if cover_data:
                async with aiofiles.open(cover_path, "wb") as f:
                    await f.write(cover_data)
            
            audio_files.sort(key=lambda x: int(re.search(r'Глава_(\d+)\.m4a', x.name).group(1)) if re.search(r'Глава_(\d+)\.m4a', x.name) else 0)
            
            async with aiofiles.open(filelist_path, 'w', encoding='utf-8') as f:
                for chapter_file in audio_files:
                    abs_path = str(chapter_file.absolute()).replace("'", "'\"'\"'")
                    await f.write(f"file '{abs_path}'\n")
            
            async with aiofiles.open(chapters_metadata_path, 'w', encoding='utf-8') as f:
                await f.write(";FFMETADATA1\n")
                
                if metadata:
                    if metadata.get("title"):
                        await f.write(f"title={self._escape(metadata['title'])}\n")
                    
                    if metadata.get("authors"):
                        await f.write(f"artist={self._escape(metadata['authors'][0])}\n")
                        if len(metadata["authors"]) > 1:
                            await f.write(f"album_artist={self._escape(', '.join(metadata['authors']))}\n")
                    
                    if metadata.get("annotation"):
                        desc = metadata["annotation"].replace("\n", " ").replace("\r", " ")[:500]
                        await f.write(f"description={self._escape(desc)}\n")
                    
                    if metadata.get("genres"):
                        genres = [g for g in metadata["genres"] if g != "Виртуальный рассказчик"]
                        if genres:
                            await f.write(f"genre={self._escape(', '.join(genres))}\n")
                    
                    if metadata.get("language"):
                        await f.write(f"language={metadata['language']}\n")
                    
                    pub_date = metadata.get("publication_date")
                    year = pub_date.split("-")[0] if pub_date and "-" in pub_date else (pub_date or str(datetime.now().year))
                    await f.write(f"date={year}\n")
                    
                    if metadata.get("owner_catalog_title"):
                        await f.write(f"copyright={self._escape(metadata['owner_catalog_title'])}\n")
                    
                    if metadata.get("age_restriction"):
                        await f.write(f"rating={metadata['age_restriction']}\n")
                    
                    if metadata.get("publishers"):
                        await f.write(f"publisher={self._escape(metadata['publishers'][0])}\n")
                    
                    if metadata.get("series_list"):
                        series = metadata["series_list"][0]
                        if series.get("title"):
                            await f.write(f"album={self._escape(series['title'])}\n")
                        if series.get("position_label"):
                            try:
                                track_num = int(float(series["position_label"]))
                                total = series.get("total_parts", 0)
                                if total > 0:
                                    await f.write(f"track={track_num}/{total}\n")
                                else:
                                    await f.write(f"track={track_num}\n")
                            except:
                                pass
                
                for i, chapter in enumerate(chapters_info):
                    chapter_num = i + 1
                    chapter_title = chapter.get("title", f"Глава {chapter_num}")
                    start_time = chapter.get("offset", 0)
                    duration = chapter.get("duration", 0)
                    
                    await f.write("\n[CHAPTER]\n")
                    await f.write("TIMEBASE=1/1000\n")
                    await f.write(f"START={int(start_time * 1000)}\n")
                    await f.write(f"END={int((start_time + duration) * 1000)}\n")
                    await f.write(f"title={chapter_title}\n")
            
            cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                   '-i', str(filelist_path), '-i', str(chapters_metadata_path)]
            
            if cover_path.exists():
                cmd.extend(['-i', str(cover_path), '-c:v', 'copy', '-c:a', 'copy',
                           '-disposition:v:0', 'attached_pic', '-map_metadata', '1'])
            else:
                cmd.extend(['-c', 'copy', '-map_metadata', '1'])
            
            if metadata:
                if metadata.get("title"):
                    cmd.extend(['-metadata', f'title={metadata["title"]}'])
                if metadata.get("authors"):
                    cmd.extend(['-metadata', f'artist={metadata["authors"][0]}'])
                if metadata.get("narrators"):
                    cmd.extend(['-metadata', f'album_artist={", ".join(metadata["narrators"])}'])
                if metadata.get("annotation"):
                    cmd.extend(['-metadata', f'description={metadata["annotation"][:500]}'])
                if metadata.get("language"):
                    cmd.extend(['-metadata', f'language={metadata["language"]}'])
                
                pub_date = metadata.get("publication_date")
                year = pub_date.split("-")[0] if pub_date and "-" in pub_date else (pub_date or str(datetime.now().year))
                cmd.extend(['-metadata', f'date={year}'])
                
                if metadata.get("owner_catalog_title"):
                    cmd.extend(['-metadata', f'copyright={metadata["owner_catalog_title"]}'])
                if metadata.get("publishers"):
                    cmd.extend(['-metadata', f'publisher={metadata["publishers"][0]}'])
                if metadata.get("source"):
                    cmd.extend(['-metadata', f'URL={metadata["source"]}'])
                
                if metadata.get("series_list"):
                    series = metadata["series_list"][0]
                    if series.get("position_label"):
                        try:
                            track_num = int(float(series["position_label"]))
                            total = series.get("total_parts", 0)
                            if total > 0:
                                cmd.extend(['-metadata', f'track={track_num}/{total}'])
                            else:
                                cmd.extend(['-metadata', f'track={track_num}'])
                        except:
                            pass
            
            cmd.append(str(temp_output))
            
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await process.communicate()
            
            if process.returncode == 0 and temp_output.exists() and temp_output.stat().st_size > 0:
                if output_path.exists():
                    output_path.unlink()
                temp_output.rename(output_path)
                return True
            else:
                return False
                    
        except Exception as e:
            console.print(f"\n   [red]Ошибка при объединении:[/red] {e}")
            return False
        finally:
            for temp_file in [filelist_path, chapters_metadata_path, cover_path, temp_output]:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except:
                        pass
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass

    @staticmethod
    def _escape(value: str) -> str:
        """Экранирование специальных символов для FFMETADATA"""
        return str(value).replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\\', '\\\\')