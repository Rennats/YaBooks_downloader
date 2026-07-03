# Yandex Books downloader
## Установка зависимостей:
*pip install -r requirements.txt*

## Авторизация в аккаунт Яндекс
Для доступа к книгам используется токен, для получения которого необходима авторизация
![Авторизация](https://github.com/kettle017/RU_Bookmate_downloader/assets/37309120/bb3453eb-5d44-4410-b2e1-05193c88333e)

## Параметры запуска скрипта:
*python YaBooks_downloader.py 'UUID/ссылка на книгу/серию/автора'*

Примеры:  
  Книга:      https://books.yandex.ru/books/UUID  
  Аудиокнига: https://books.yandex.ru/audiobooks/UUID  
  Комикс:     https://books.yandex.ru/comicbooks/UUID  
  Серия:      https://books.yandex.ru/series/UUID  
  Автор:      https://books.yandex.ru/authors/UUID  

## Скачанные книги
Скачанные в процессе работы книги загружаются в подпапку MyBooks папки запуска скрипта.
При этом в ней организуются подпапки по имени автора (Фамилия Имя), внутри которой создаются подпапки по сериям, книги без серий расположены в корне папки автора
