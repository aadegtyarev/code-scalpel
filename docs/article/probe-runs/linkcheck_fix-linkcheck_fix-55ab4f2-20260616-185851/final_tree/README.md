# link-checker

Скрипт для поиска и проверки ссылок в Markdown-файлах.

Ищет все `.md` файлы в указанной директории, извлекает из них ссылки
(inline, autolink, reference-style) и проверяет их доступность:
HTTP/HTTPS-ссылки — через HEAD/GET-запросы, относительные — проверкой
наличия файла на диске.

## Использование

```bash
python link_checker.py --help
```

### Извлечение ссылок

Вывести все найденные ссылки из `.md` файлов без проверки доступности:

```bash
python link_checker.py --extract
```

Указать корневую директорию (по умолчанию — текущая):

```bash
python link_checker.py --extract --root docs/
```

Пример вывода:

```
# readme.md
  [inline] https://python.org
  [autolink] https://docs.python.org
  [reference] https://example.com

# docs/guide.md
  [inline] ../images/logo.png
```

### Проверка доступности

Проверить все ссылки и показать статус каждой:

```bash
python link_checker.py --check
```

С указанием корня:

```bash
python link_checker.py --check --root docs/
```

Пример вывода:

```
  ✓ readme.md:1  https://python.org              →  200 OK
  ✓ docs/guide.md:5  ../images/logo.png           →  файл найден
  ✗ docs/guide.md:12  https://example.com/broken  →  404 Not Found

Проверено: 42, доступно: 40, битых: 2
```

Если найдены битые ссылки, скрипт завершается с ненулевым кодом возврата.

## Структура проекта

- `link_checker.py` — точка входа
- `cli.py` — CLI (разбор аргументов, команды)
- `link_parser.py` — парсинг Markdown и извлечение ссылок
- `http_client.py` — HTTP-клиент и проверка файлов

## Зависимости

- Python 3.10+
- [requests](https://pypi.org/project/requests/)
