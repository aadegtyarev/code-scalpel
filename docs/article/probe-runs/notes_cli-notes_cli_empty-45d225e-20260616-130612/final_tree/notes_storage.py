"""Модуль хранения заметок в JSON-файле."""

import json
import os

_STORAGE_FILE = "notes.json"


def _load() -> list[dict]:
    """Загрузить все заметки из файла. Если файла нет или он пуст — вернуть []."""
    if not os.path.exists(_STORAGE_FILE):
        return []
    try:
        with open(_STORAGE_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                return []
            return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return []


def _save(notes: list[dict]) -> None:
    """Сохранить список заметок в файл."""
    with open(_STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)


def add_note(title: str, content: str) -> int:
    """Добавить заметку и вернуть её id."""
    notes = _load()
    note_id = max((n["id"] for n in notes), default=0) + 1
    notes.append({"id": note_id, "title": title, "content": content})
    _save(notes)
    return note_id


def list_notes() -> list[dict]:
    """Вернуть список всех заметок."""
    return _load()


def search_notes(query: str) -> list[dict]:
    """Вернуть заметки, в заголовке или содержимом которых есть query (без учёта регистра)."""
    q = query.lower()
    return [n for n in _load() if q in n["title"].lower() or q in n["content"].lower()]


def delete_note(note_id: int) -> bool:
    """Удалить заметку по id. Вернуть True, если удалена, False — если не найдена."""
    notes = _load()
    for i, n in enumerate(notes):
        if n["id"] == note_id:
            notes.pop(i)
            _save(notes)
            return True
    return False
