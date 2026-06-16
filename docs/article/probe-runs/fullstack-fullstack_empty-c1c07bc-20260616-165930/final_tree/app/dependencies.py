from collections.abc import AsyncGenerator

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db as _get_db
from app.rate_limiter import RateLimiter


async def get_redis() -> AsyncGenerator[Redis, None]:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield redis
    finally:
        await redis.aclose()


async def get_rate_limiter(
    redis: Redis = Depends(get_redis),
) -> RateLimiter:
    return RateLimiter(redis_client=redis)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in _get_db():
        yield session
