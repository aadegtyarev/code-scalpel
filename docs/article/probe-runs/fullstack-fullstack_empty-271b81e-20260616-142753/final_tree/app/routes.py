from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ApiKey, generate_key, hash_key
from app.rate_limiter import RateLimiter
from app.redis_client import get_redis
from app.schemas import KeyOut, KeyResponse, VerifyRequest, VerifyResponse

router = APIRouter()


def check_rate_limit(
    request: Request,
    redis=Depends(get_redis),
):
    """Dependency that enforces sliding-window rate limiting by IP."""
    rl = RateLimiter(
        redis,
        requests=settings.rate_limit_requests,
        window=settings.rate_limit_window,
    )
    client_ip = request.client.host
    allowed, retry_after = rl.is_allowed(f"rl:{client_ip}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


@router.post("/keys", response_model=KeyResponse, status_code=201)
def create_key(
    db: Session = Depends(get_db),
    _=Depends(check_rate_limit),
):
    key = generate_key()
    key_hash = hash_key(key)
    db_key = ApiKey(key_hash=key_hash)
    db.add(db_key)
    db.commit()
    db.refresh(db_key)
    return KeyResponse(id=db_key.id, key=key, created_at=db_key.created_at)


@router.get("/keys", response_model=list[KeyOut])
def list_keys(db: Session = Depends(get_db)):
    keys = db.query(ApiKey).all()
    return [
        KeyOut(
            id=k.id,
            key_hash=k.key_hash,
            created_at=k.created_at,
            is_active=k.is_active,
        )
        for k in keys
    ]


@router.delete("/keys/{key_id}", status_code=204)
def delete_key(key_id: int, db: Session = Depends(get_db)):
    db_key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not db_key:
        raise HTTPException(status_code=404, detail="Key not found")
    db.delete(db_key)
    db.commit()


@router.post("/verify", response_model=VerifyResponse)
def verify_key(
    body: VerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
    redis=Depends(get_redis),
):
    rl = RateLimiter(
        redis,
        requests=settings.rate_limit_requests,
        window=settings.rate_limit_window,
    )
    client_ip = request.client.host
    allowed, retry_after = rl.is_allowed(f"rl:verify:{client_ip}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    key_hash = hash_key(body.key)
    exists = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first() is not None
    return VerifyResponse(valid=exists)
