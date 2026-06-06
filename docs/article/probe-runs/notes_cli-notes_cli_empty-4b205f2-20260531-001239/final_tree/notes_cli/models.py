from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(slots=True)
class Note:
    id: str
    title: str
    text: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "Note":
        return cls(
            id=data["id"],
            title=data["title"],
            text=data["text"],
            created_at=data["created_at"],
        )
