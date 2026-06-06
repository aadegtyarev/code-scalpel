"""Модуль хранения данных заметок."""

import json
import os
from datetime import datetime, timezone
from typing import Any


DEFAULT_STORAGE_PATH = "notes.json"


def load_notes(path: str | None = None) -> list[dict[str, Any]]:
    """Загрузить заметки из JSON-файла.

    Если файл не существует, возвращает пустой список.
    """
    if path is None:
        path = DEFAULT_STORAGE_PATH
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_notes(notes: list[dict[str, Any]], path: str | None = None) -> None:
    """Сохранить список заметок в JSON-файл."""
    if path is None:
        path = DEFAULT_STORAGE_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)


def add_note(text: str, title: str = "", path: str | None = None) -> dict[str, Any]:
    """Добавить заметку и вернуть её."""
    notes = load_notes(path)
    new_id = get_next_id(notes)
    note = {
        "id": new_id,
        "title": title,
        "text": text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    notes.append(note)
    save_notes(notes, path)
    return note


def delete_note(note_id: int, path: str | None = None) -> bool:
    """Удалить заметку по ID. Возвращает True, если найдена и удалена."""
    notes = load_notes(path)
    for i, note in enumerate(notes):
        if note["id"] == note_id:
            notes.pop(i)
            save_notes(notes, path)
            return True
    return False


def search_notes(keyword: str, path: str | None = None) -> list[dict[str, Any]]:
    """Найти заметки, содержащие keyword в title или text."""
    notes = load_notes(path)
    keyword_lower = keyword.lower()
    return [
        note
        for note in notes
        if keyword_lower in note.get("title", "").lower()
        or keyword_lower in note.get("text", "").lower()
    ]


def get_next_id(notes: list[dict[str, Any]]) -> int:
    """Вернуть следующий свободный ID для новой заметки."""
    if not notes:
        return 1
    return max(note["id"] for note in notes) + 1
