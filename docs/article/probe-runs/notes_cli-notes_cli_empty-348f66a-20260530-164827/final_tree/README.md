# CLI для заметок

## Команды:

- **add**: добавить новую заметку
  ```bash
  python notes.py add "Текст заметки"
  ```

- **list**: вывести все заметки
  ```bash
  python notes.py list
  ```

- **search**: найти заметки по ключевому слову
  ```bash
  python notes.py search "ключевое_слово"
  ```

- **delete**: удалить заметку по идентификатору
  ```bash
  python notes.py delete <идентификатор>
  ```

## Формат данных:

Заметки хранятся в JSON-файле `notes.json` с следующей структурой:
```json
[
    {
        "id": 1,
        "text": "Текст заметки"
    }
]
```