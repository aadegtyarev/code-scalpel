import time


class RateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(self, redis, requests: int, window: int):
        self.redis = redis
        self.requests = requests
        self.window = window  # seconds

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.time()
        cutoff = now - self.window

        self.redis.zremrangebyscore(key, 0, cutoff)
        count = self.redis.zcard(key)

        if count >= self.requests:
            oldest = self.redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                retry_after = int(self.window - (now - oldest[0][1])) + 1
            else:
                retry_after = self.window
            return False, retry_after

        self.redis.zadd(key, {str(now): now})
        self.redis.expire(key, self.window)
        return True, 0
