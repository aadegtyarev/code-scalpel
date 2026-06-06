# notes-cli

Python CLI для управления заметками с хранением в JSON.

## Установка

```bash
pip install -e .
```

## Команды

### add

Добавить новую заметку.

```bash
notes add --title "Заголовок" --text "Текст заметки"
```

### list

Вывести все заметки.

```bash
notes list
```

### search

Найти заметки по ключевому слову.

```bash
notes search --keyword "python"
```

### delete

Удалить заметку по ID.

```bash
notes delete --id 1
```

## Формат хранения

Данные хранятся в JSON-файле `notes.json` в текущей директории.

Каждая заметка имеет структуру:

```json
{
  "id": 1,
  "title": "Заголовок",
  "text": "Текст заметки",
  "created_at": "2024-01-01T12:00:00"
}
```
