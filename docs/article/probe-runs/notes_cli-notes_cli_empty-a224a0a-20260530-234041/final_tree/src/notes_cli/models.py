from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Note:
    id: str
    title: str
    content: str
    created_at: str

    @classmethod
    def create(cls, note_id: str, title: str, content: str) -> "Note":
        return cls(
            id=note_id,
            title=title,
            content=content,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def matches(self, query: str) -> bool:
        needle = query.casefold()
        return needle in self.title.casefold() or needle in self.content.casefold()

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "Note":
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            content=data.get("content", ""),
            created_at=data["created_at"],
        )
