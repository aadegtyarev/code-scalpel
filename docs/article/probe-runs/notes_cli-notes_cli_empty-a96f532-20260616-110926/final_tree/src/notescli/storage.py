"""JSON-based storage for notes."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _default_path() -> Path:
    return Path.cwd() / "notes.json"


def _load_notes(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            raise RuntimeError(
                f"Файл {path} содержит не список (ожидался JSON-массив)"
            )
        return data
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Ошибка чтения {path}: повреждён JSON ({e})")


def _dump_notes(notes: list[dict[str, Any]], path: Path) -> None:
    path.write_text(
        json.dumps(notes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_note(title: str, content: str, storage_path: str | Path | None = None) -> str:
    """Добавить заметку. Возвращает её ID."""
    path = Path(storage_path) if storage_path else _default_path()
    notes = _load_notes(path)
    note_id = str(uuid.uuid4())
    note = {
        "id": note_id,
        "title": title,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    notes.append(note)
    _dump_notes(notes, path)
    return note_id


def list_notes(
    storage_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Вернуть все заметки, отсортированные по дате создания."""
    path = Path(storage_path) if storage_path else _default_path()
    notes = _load_notes(path)
    return sorted(notes, key=lambda n: n.get("created_at", ""))


def search_notes(
    query: str,
    storage_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Вернуть заметки, где query входит в title или content."""
    path = Path(storage_path) if storage_path else _default_path()
    notes = _load_notes(path)
    q = query.lower()
    return [
        n
        for n in notes
        if q in n.get("title", "").lower() or q in n.get("content", "").lower()
    ]


def delete_note(
    note_id: str,
    storage_path: str | Path | None = None,
) -> bool:
    """Удалить заметку по ID. Вернуть True, если заметка найдена и удалена."""
    path = Path(storage_path) if storage_path else _default_path()
    notes = _load_notes(path)
    before = len(notes)
    notes = [n for n in notes if n.get("id") != note_id]
    if len(notes) == before:
        return False
    _dump_notes(notes, path)
    return True
