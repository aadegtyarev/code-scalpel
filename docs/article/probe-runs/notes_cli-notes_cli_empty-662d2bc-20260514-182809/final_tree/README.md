# Notes CLI

Этот проект представляет собой простой CLI для управления заметками.

## Установка

1. Убедитесь, что у вас установлен Python 3.x и pip.
2. Клонируйте репозиторий:
   ```bash
   git clone <URL_РЕПОЗИТОРИЯ>
   cd notes-cli
   ```
3. Создайте виртуальное окружение и активируйте его:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Для Unix/macOS
   .venv\Scripts\activate     # Для Windows
   ```
4. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
5. Запустите тесты (опционально):
   ```bash
   pytest
   ```

## Использование

### Добавление заметки
Для добавления новой заметки используйте команду `add`:
```bash
python notes.py add "Моя первая заметка"
```

### Список всех заметок
Для вывода списка всех заметок используйте команду `list`:
```bash
python notes.py list
```

### Поиск заметок по ключевому слову
Для поиска заметок по ключевому слову используйте команду `search`:
```bash
python notes.py search "первый"
```

### Удаление заметки по индексу
Для удаления заметки по её индексу в списке используйте команду `delete`:
```bash
python notes.py delete 0
```

## Примеры использования

1. Добавление нескольких заметок и вывод списка:
   ```bash
   python notes.py add "Заметка 1"
   python notes.py add "Заметка 2"
   python notes.py list
   ```

2. Поиск заметки по ключевому слову и удаление её по индексу:
   ```bash
   python notes.py search "заметка"
   python notes.py delete 0
   ```