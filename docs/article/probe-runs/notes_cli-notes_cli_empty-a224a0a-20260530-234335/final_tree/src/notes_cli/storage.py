"""Хранение заметок в JSON-файле."""

import json
from pathlib import Path
from typing import Any


class NoteStorage:
    """CRUD-операции с заметками, хранящимися в JSON-файле."""

    def __init__(self, path: str | Path = "notes.json") -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        """Загрузить данные из JSON-файла. Если файла нет — вернуть пустую структуру."""
        if not self.path.exists():
            return {"notes": [], "next_id": 1}
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict[str, Any]) -> None:
        """Сохранить данные в JSON-файл."""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add(self, text: str) -> int:
        """Сохранить заметку. Возвращает её ID."""
        data = self._load()
        note_id = data["next_id"]
        data["notes"].append({"id": note_id, "text": text})
        data["next_id"] = note_id + 1
        self._save(data)
        return note_id

    def list_all(self) -> list[dict[str, Any]]:
        """Вернуть все заметки."""
        data = self._load()
        return data["notes"]

    def search(self, query: str) -> list[dict[str, Any]]:
        """Вернуть заметки, содержащие query (регистронезависимо)."""
        data = self._load()
        query_lower = query.lower()
        return [n for n in data["notes"] if query_lower in n["text"].lower()]

    def delete(self, note_id: int) -> bool:
        """Удалить заметку по ID. Возвращает True, если найдена и удалена."""
        data = self._load()
        for i, note in enumerate(data["notes"]):
            if note["id"] == note_id:
                data["notes"].pop(i)
                self._save(data)
                return True
        return False
