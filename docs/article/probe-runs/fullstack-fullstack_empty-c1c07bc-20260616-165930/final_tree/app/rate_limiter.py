import time
import uuid
from typing import Tuple

from redis.asyncio import Redis

from app.config import settings


class RateLimiter:
    """Sliding window rate limiter backed by Redis sorted sets.

    Uses a sorted set per identifier (e.g. IP address) where members
    are unique request IDs and scores are timestamps. Old entries
    outside the window are pruned before counting.
    """

    def __init__(
        self,
        redis_client: Redis,
        limit: int = settings.rate_limit_requests,
        window_seconds: int = settings.rate_limit_window_seconds,
    ):
        self.redis = redis_client
        self.limit = limit
        self.window = window_seconds

    async def check(self, identifier: str) -> Tuple[bool, dict]:
        """Check if a request from *identifier* is allowed.

        Returns ``(allowed, info)`` where *info* contains:
        * ``limit`` — max requests per window
        * ``remaining`` — requests remaining in the current window
        * ``reset`` — unix timestamp when the window resets
        """
        now = time.time()
        window_start = now - self.window
        key = f"ratelimit:{identifier}"

        # 1. Prune entries outside the sliding window
        await self.redis.zremrangebyscore(key, 0, window_start)  # type: ignore[arg-type]

        # 2. Count entries still in the window
        count = await self.redis.zcard(key)  # type: ignore[arg-type]

        if count >= self.limit:
            allowed = False
            # Leave the set as-is; TTL will clean it eventually
        else:
            allowed = True
            member = str(uuid.uuid4())
            pipe = self.redis.pipeline()
            pipe.zadd(key, {member: now})  # type: ignore[arg-type]
            pipe.expire(key, self.window + 2)
            await pipe.execute()

        remaining = max(0, self.limit - (count + 1 if allowed else count))
        reset = int(now - (now % 1) + self.window)  # ceiling to next window boundary

        info = {
            "limit": self.limit,
            "remaining": remaining,
            "reset": reset,
        }
        return allowed, info
