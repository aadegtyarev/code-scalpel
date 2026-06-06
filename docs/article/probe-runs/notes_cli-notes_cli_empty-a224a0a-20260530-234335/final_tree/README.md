# notes-cli

Python CLI-утилита для управления заметками с хранением в JSON.

## Установка

```bash
pip install -e .
```

## Команды

### add

Создать новую заметку.

```bash
notes add "Текст заметки"
```

### list

Вывести все заметки.

```bash
notes list
```

### search

Найти заметки по ключевым словам.

```bash
notes search "ключевое слово"
```

### delete

Удалить заметку по ID.

```bash
notes delete 1
```

## Формат хранения

Данные хранятся в JSON-файле `notes.json` в текущей директории.
