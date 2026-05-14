# Notes CLI

## Описание
Этот проект представляет собой простой Python-CLI для управления заметками. Поддерживаются команды `add`, `list`, `search` и `delete`. Заметки хранятся в JSON-файле.

## Установка
1. Клонируйте репозиторий:
   ```bash
   git clone <repository-url>
   cd notes-cli
   ```
2. Создайте и активируйте виртуальное окружение:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
4. Запустите CLI:
   ```bash
   python notes_cli.py add 'My first note'
   python notes_cli.py list
   python notes_cli.py search 'first'
   python notes_cli.py delete 1
   ```