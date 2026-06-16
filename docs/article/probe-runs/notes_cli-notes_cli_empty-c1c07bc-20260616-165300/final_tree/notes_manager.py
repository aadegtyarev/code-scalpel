"""Модуль управления заметками с JSON-хранилищем."""

import json
import os
from datetime import datetime, timezone


def load_notes(path: str) -> list[dict]:
    """Загрузить заметки из JSON-файла. Если файла нет — вернуть пустой список."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_notes(notes: list[dict], path: str) -> None:
    """Сохранить список заметок в JSON-файл."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)


def _next_id(notes: list[dict]) -> int:
    """Вернуть следующий свободный ID (макс id + 1, или 1 если список пуст)."""
    if not notes:
        return 1
    return max(n["id"] for n in notes) + 1


def add_note(text: str, path: str) -> dict:
    """Добавить заметку и сохранить. Вернуть добавленную заметку."""
    notes = load_notes(path)
    note = {
        "id": _next_id(notes),
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    notes.append(note)
    save_notes(notes, path)
    return note


def list_notes(path: str) -> list[dict]:
    """Вернуть список всех заметок из файла."""
    return load_notes(path)


def search_notes(text: str, path: str) -> list[dict]:
    """Вернуть заметки, в тексте которых содержится искомая строка (регистронезависимо)."""
    notes = load_notes(path)
    text_lower = text.lower()
    return [n for n in notes if text_lower in n["text"].lower()]


def delete_note(note_id: int, path: str) -> bool:
    """Удалить заметку по ID. Вернуть True если удалена, False если ID не найден."""
    notes = load_notes(path)
    for i, n in enumerate(notes):
        if n["id"] == note_id:
            notes.pop(i)
            save_notes(notes, path)
            return True
    return False
