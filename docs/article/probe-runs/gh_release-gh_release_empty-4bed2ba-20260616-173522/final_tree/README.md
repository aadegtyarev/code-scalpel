# GitHub Release Publisher CLI

Утилита для публикации GitHub-релизов на основе `CHANGELOG.md`. Парсит changelog, создаёт релиз через GitHub REST API и загружает бинарники (asset'ы).

## Команды

### `publish`

Создаёт GitHub Release на основе последней записи в `CHANGELOG.md`.

```bash
# Обычный запуск — парсит CHANGELOG.md, создаёт релиз, загружает asset'ы
publish-github-release publish --repo owner/repo --assets ./dist/*.tar.gz

# Сухой прогон — показывает, что будет сделано, без вызовов API
publish-github-release publish --repo owner/repo --dry-run

# Можно указать конкретный файл changelog
publish-github-release publish --repo owner/repo --changelog ./docs/CHANGELOG.md

# Несколько asset'ов
publish-github-release publish \
  --repo owner/repo \
  --assets ./dist/app-linux-amd64 \
  --assets ./dist/app-darwin-amd64
```

### `list`

Выводит список опубликованных релизов для указанного репозитория.

```bash
# Список всех релизов
publish-github-release list --repo owner/repo

# Релиз можно задать через переменную окружения GITHUB_REPOSITORY
export GITHUB_REPOSITORY=owner/repo
publish-github-release list
```

## Формат CHANGELOG.md

Парсер ориентируется на формат [Keep a Changelog](https://keepachangelog.com/).

### Правила парсинга

1. Заголовки версий записываются как `## [version] - YYYY-MM-DD`  
   Пример: `## [1.2.3] - 2025-06-01`

2. Извлекается **последняя** (ближайшая к началу файла) запись:
   - `version` — номер версии без скобок (например, `1.2.3`)
   - `body` — всё содержимое между заголовком этой версии и следующим заголовком (или концом файла)
   - `date` — дата выпуска (строка после дефиса)

3. Строки до первого заголовка версии игнорируются (преамбула, ссылки и т.д.)

4. Если в файле нет ни одного подходящего заголовка — возвращается ошибка.

### Пример CHANGELOG.md

```markdown
# Changelog

## [1.2.0] - 2025-05-15

### Added
- Новый эндпоинт для поиска
- Поддержка пагинации

### Fixed
- Исправлена утечка соединений

## [1.1.0] - 2025-04-01

### Added
- Первый публичный релиз
```

При публикации с этим changelog'ом будет взята версия `1.2.0` за `2025-05-15` с телом релиза от `## [1.2.0]` до `## [1.1.0]`.

## Переменные окружения

| Переменная | Обязательная | Описание |
|---|---|---|
| `GITHUB_TOKEN` | Да (кроме `--dry-run`) | Personal access token с правами `repo` |
| `GITHUB_REPOSITORY` | Нет | Репозиторий в формате `owner/repo` (можно передать через `--repo`) |

## Аутентификация

Токен передаётся в HTTP-заголовке `Authorization: Bearer <token>`. Токен должен иметь как минимум разрешение `repo` (для приватных репозиториев) или `public_repo` (для публичных).

## Структура проекта

```
github_release_publisher/
├── __init__.py
├── changelog.py        # Парсинг CHANGELOG.md
├── github_client.py    # HTTP-клиент GitHub REST API
├── cli.py              # Точка входа CLI (click)
tests/
├── __init__.py
├── test_changelog.py
├── test_github_client.py
├── test_cli.py
```
