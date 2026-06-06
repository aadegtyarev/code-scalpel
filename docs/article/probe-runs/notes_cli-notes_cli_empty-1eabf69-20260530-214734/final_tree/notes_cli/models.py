from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Note:
    id: Optional[int] = None
    title: str = ""
    content: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
