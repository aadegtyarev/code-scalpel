from datetime import datetime

from pydantic import BaseModel


class KeyCreate(BaseModel):
    pass


class KeyResponse(BaseModel):
    id: int
    key: str
    created_at: datetime


class KeyOut(BaseModel):
    id: int
    key_hash: str
    created_at: datetime
    is_active: bool


class VerifyRequest(BaseModel):
    key: str


class VerifyResponse(BaseModel):
    valid: bool
