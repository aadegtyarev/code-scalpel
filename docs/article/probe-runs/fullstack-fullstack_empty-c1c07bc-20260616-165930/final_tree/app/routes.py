import hashlib
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_rate_limiter
from app.models import Key
from app.rate_limiter import RateLimiter
from app.schemas import KeyCreateResponse, KeyOut, VerifyRequest, VerifyResponse

router = APIRouter()


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@router.post("/keys", status_code=201)
async def create_key(
    db: AsyncSession = Depends(get_db),
) -> KeyCreateResponse:
    """Generate a new API key, store its SHA-256 hash, return the raw key once."""
    raw_key = "ak_" + secrets.token_hex(32)
    key_hash = _hash_key(raw_key)
    key_record = Key(key_hash=key_hash)
    db.add(key_record)
    await db.flush()
    await db.refresh(key_record)
    return KeyCreateResponse(id=key_record.id, key=raw_key)


@router.get("/keys")
async def list_keys(
    db: AsyncSession = Depends(get_db),
) -> list[KeyOut]:
    """Return all active keys (id and created_at only, no hash)."""
    result = await db.execute(
        select(Key).where(Key.is_active == True).order_by(Key.created_at.desc())
    )
    keys = result.scalars().all()
    return [KeyOut(id=k.id, created_at=k.created_at) for k in keys]


@router.delete("/keys/{key_id}", status_code=204)
async def deactivate_key(
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a key by setting is_active = False."""
    result = await db.execute(select(Key).where(Key.id == key_id))
    key_record = result.scalar_one_or_none()
    if key_record is None:
        raise HTTPException(status_code=404, detail="Key not found")
    key_record.is_active = False
    await db.flush()


@router.post("/verify")
async def verify_key(
    body: VerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> JSONResponse:
    """Verify a raw key against stored SHA-256 hashes. Rate-limited per IP."""
    client_ip = request.client.host if request.client else "unknown"

    # --- sliding window rate check ---
    allowed, info = await rate_limiter.check(client_ip)
    if not allowed:
        return JSONResponse(
            status_code=403,
            content={"detail": "Rate limit exceeded"},
            headers={
                "X-RateLimit-Limit": str(info["limit"]),
                "X-RateLimit-Remaining": str(info["remaining"]),
                "X-RateLimit-Reset": str(info["reset"]),
            },
        )

    # --- verify the key ---
    key_hash = _hash_key(body.key)
    result = await db.execute(
        select(Key).where(Key.key_hash == key_hash, Key.is_active == True)
    )
    key_record = result.scalar_one_or_none()
    if key_record is None:
        return JSONResponse(
            status_code=403,
            content={"detail": "Invalid or inactive key"},
        )

    return JSONResponse(
        content=VerifyResponse(valid=True).model_dump(),
        headers={
            "X-RateLimit-Limit": str(info["limit"]),
            "X-RateLimit-Remaining": str(info["remaining"]),
            "X-RateLimit-Reset": str(info["reset"]),
        },
    )
