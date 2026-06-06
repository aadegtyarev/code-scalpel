# Notes CLI

Python-CLI для управления заметками с JSON-хранилищем.

## Установка

```bash
pip install -e .
```

## Команды

### add

Добавить новую заметку.

```bash
notes add "Текст заметки"
```

### list

Вывести все заметки.

```bash
notes list
```

### search

Найти заметки по ключевому слову.

```bash
notes search "ключевое слово"
```

### delete

Удалить заметку по ID.

```bash
notes delete 1
```

## Хранение данных

Заметки хранятся в JSON-файле `notes.json` в текущей директории.
