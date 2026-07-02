# src/config.py
"""Конфигурация и константы"""
import random
from pathlib import Path

BASE_URL = "https://api.bookmate.yandex.net/api/v5"

MYBOOKS_DIR = Path("MyBooks")
MYBOOKS_DIR.mkdir(exist_ok=True)

MAX_CONCURRENT_DOWNLOADS = 3
MAX_AUDIO_DOWNLOADS = 6

TITLE_MAX_LENGTH = 60

UA = {
    1: "Samsung/Galaxy_A51 Android/12 Bookmate/6.66.0",
    2: "Huawei/P40_Lite Android/11 Bookmate/6.66.0",
    3: "OnePlus/Nord_N10 Android/10 Bookmate/6.66.0",
    4: "Google/Pixel_4a Android/9 Bookmate/6.66.0",
    5: "Oppo/Reno_4 Android/8 Bookmate/6.66.0",
    6: "Xiaomi/Redmi_Note_9 Android/10 Bookmate/6.66.0",
    7: "Motorola/Moto_G_Power Android/10 Bookmate/6.66.0",
    8: "Sony/Xperia_10 Android/10 Bookmate/6.66.0",
    9: "LG/Velvet Android/10 Bookmate/6.66.0",
    10: "Realme/6_Pro Android/10 Bookmate/6.66.0",
}

HEADERS = {
    "app-user-agent": UA[random.randint(1, 10)],
    "auth-token": "",
    "user-agent": "",
}

URLS = {
    "series_parts": f"{BASE_URL}/series/{{uuid}}/parts?per_page=500",
    "books_info": f"{BASE_URL}/books/{{uuid}}",
    "audiobooks_info": f"{BASE_URL}/audiobooks/{{uuid}}",
    "comicbooks_info": f"{BASE_URL}/comicbooks/{{uuid}}",
    "book_content": f"{BASE_URL}/books/{{uuid}}/content/v4",
    "audiobook_playlist": f"{BASE_URL}/audiobooks/{{uuid}}/playlists.json",
    "comicbook_meta": f"{BASE_URL}/comicbooks/{{uuid}}/metadata.json",
    "author_books": f"{BASE_URL}/authors/{{uuid}}/books?role=author&per_page=500",
    "author_audiobooks": f"{BASE_URL}/authors/{{uuid}}/audiobooks?role=author&per_page=500",
    "author_comicbooks": f"{BASE_URL}/authors/{{uuid}}/comicbooks?role=author&per_page=500",
}