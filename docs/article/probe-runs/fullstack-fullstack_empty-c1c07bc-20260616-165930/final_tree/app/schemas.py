from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class KeyCreateResponse(BaseModel):
    id: UUID
    key: str


class KeyOut(BaseModel):
    id: UUID
    created_at: datetime


class VerifyRequest(BaseModel):
    key: str


class VerifyResponse(BaseModel):
    valid: bool
