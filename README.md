# Yandex Books downloader
## Установка зависимостей:
*pip install -r requirements.txt*

Для загрузки аудиокниг требуется установленный в системе FFmpeg (https://www.ffmpeg.org/download.html)  
Для Windows 10/11 удобно его установить командой в PowerShell: *winget install ffmpeg*  

## Авторизация в аккаунт Яндекс
Для доступа к книгам используется токен, для получения которого необходима авторизация  
![Авторизация](https://github.com/kettle017/RU_Bookmate_downloader/assets/37309120/bb3453eb-5d44-4410-b2e1-05193c88333e)

## Параметры запуска скрипта:
*python YaBooks_downloader.py [ПАРАМЕТРЫ] [ССЫЛКА]*

__Параметры:__  
  *--max_bitrate*&ensp;&ensp;&ensp;Загрузка аудиокниг в максимальном качестве  
  *--min_bitrate*&ensp;&ensp;&ensp;Загрузка аудиокниг в минимальном качестве  

__Ссылка может быть на:__  
  книгу&ensp;&ensp;&ensp;&ensp;&ensp;&ensp;&ensp; - https://books.yandex.ru/books/UUID  
  аудиокнигу&ensp;&ensp;&ensp; - https://books.yandex.ru/audiobooks/UUID  
  комикс&ensp;&ensp;&ensp;&ensp;&ensp;&ensp; - https://books.yandex.ru/comicbooks/UUID  
  серию&ensp;&ensp;&ensp;&ensp;&ensp;&ensp; - https://books.yandex.ru/series/UUID  
  автора&ensp;&ensp;&ensp;&ensp;&ensp;&ensp; - https://books.yandex.ru/authors/UUID  

__Примеры:__  
  *python YaBooks_downloader.py AbCd1234*  
  *python YaBooks_downloader.py --min_bitrate https://books.yandex.ru/audiobooks/AbCd1234*  
  *python YaBooks_downloader.py (интерактивный режим)*  

## Скачанные книги
Скачанные в процессе работы книги загружаются в подпапку MyBooks папки запуска скрипта.  
При этом в ней организуются подпапки по имени автора (Фамилия Имя), внутри которой создаются подпапки по сериям, книги без серий расположены в корне папки автора  