# CLI для заметок

Этот проект представляет собой простой Python-CLI для управления заметками. Заметки хранятся в формате JSON.

## Команды

1. **add**
   Добавляет новую заметку.
   ```bash
   python notes.py add "Текст заметки"
   ```

2. **list**
   Выводит все заметки.
   ```bash
   python notes.py list
   ```

3. **search**
   Ищет заметки по ключевым словам.
   ```bash
   python notes.py search "ключевое слово"
   ```

4. **delete**
   Удаляет заметку по индексу.
   ```bash
   python notes.py delete 1
   ```