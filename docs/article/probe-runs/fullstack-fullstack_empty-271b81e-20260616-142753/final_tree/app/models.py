import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base


def generate_key() -> str:
    """Generate a random API key with ak_ prefix."""
    return "ak_" + uuid.uuid4().hex


def hash_key(key: str) -> str:
    """Return SHA-256 hex digest of the given key."""
    return hashlib.sha256(key.encode()).hexdigest()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)
