from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class Note:
    id: str
    title: str
    body: str
    created_at: str

    @classmethod
    def create(cls, note_id: str, title: str, body: str = "") -> "Note":
        return cls(
            id=note_id,
            title=title,
            body=body,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "Note":
        return cls(
            id=data["id"],
            title=data["title"],
            body=data.get("body", ""),
            created_at=data["created_at"],
        )
