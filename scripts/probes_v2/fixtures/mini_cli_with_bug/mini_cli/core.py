"""Бизнес-логика todo-list: одна модель + JSON-хранилище."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Todo:
    """Одна запись. `id` — порядковый, выдаётся при `add`. `done`
    переключается командой `done`."""

    id: int
    text: str
    done: bool = False


class TodoStore:
    """JSON-файл как хранилище. Все методы атомарные через
    write_text — для probe-fixture'ы достаточно, конкурентного
    доступа нет."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> list[Todo]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text())
        return [Todo(**item) for item in raw]

    def _write(self, items: list[Todo]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(t) for t in items], indent=2))

    def list(self) -> list[Todo]:
        return self._read()

    def add(self, text: str) -> Todo:
        items = self._read()
        next_id = (max((t.id for t in items), default=0)) + 1
        item = Todo(id=next_id, text=text)
        items.append(item)
        self._write(items)
        return item

    def mark_done(self, todo_id: int) -> Todo | None:
        items = self._read()
        for item in items:
            if item.id == todo_id:
                item.done = True
                return item
        return None

    def remove(self, todo_id: int) -> bool:
        items = self._read()
        before = len(items)
        items = [t for t in items if t.id != todo_id]
        if len(items) == before:
            return False
        self._write(items)
        return True
