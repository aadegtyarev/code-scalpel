import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.rate_limiter import RateLimiter


@pytest.fixture
def redis_mock() -> MagicMock:
    return MagicMock()


@pytest.fixture
def limiter(redis_mock: MagicMock) -> RateLimiter:
    return RateLimiter(redis_client=redis_mock, limit=3, window_seconds=60)


def _setup_pipeline(redis_mock: MagicMock) -> MagicMock:
    """Configure redis_mock.pipeline() to return a mock with async execute."""
    pipeline_mock = MagicMock()
    pipeline_mock.zadd = MagicMock()
    pipeline_mock.expire = MagicMock()
    pipeline_mock.execute = AsyncMock()
    redis_mock.pipeline = MagicMock(return_value=pipeline_mock)
    return pipeline_mock


@pytest.mark.asyncio
async def test_allowed_when_under_limit(redis_mock: MagicMock, limiter: RateLimiter) -> None:
    """Request is allowed when count is below the limit."""
    redis_mock.zremrangebyscore = AsyncMock()
    redis_mock.zcard = AsyncMock(return_value=0)
    _setup_pipeline(redis_mock)

    allowed, info = await limiter.check("127.0.0.1")

    assert allowed is True
    assert info["limit"] == 3
    assert info["remaining"] >= 0
    redis_mock.zremrangebyscore.assert_awaited_once()
    redis_mock.zcard.assert_awaited_once()
    assert redis_mock.pipeline.called


@pytest.mark.asyncio
async def test_blocked_when_at_limit(redis_mock: MagicMock, limiter: RateLimiter) -> None:
    """Request is blocked when count already equals the limit."""
    redis_mock.zremrangebyscore = AsyncMock()
    redis_mock.zcard = AsyncMock(return_value=3)

    allowed, info = await limiter.check("127.0.0.1")

    assert allowed is False
    assert info["remaining"] == 0
    # Should NOT have added a new entry
    redis_mock.pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_blocked_when_over_limit(redis_mock: MagicMock, limiter: RateLimiter) -> None:
    """Request is blocked when count exceeds the limit."""
    redis_mock.zremrangebyscore = AsyncMock()
    redis_mock.zcard = AsyncMock(return_value=5)

    allowed, info = await limiter.check("127.0.0.1")

    assert allowed is False
    assert info["remaining"] == 0


@pytest.mark.asyncio
async def test_reset_time_is_in_future(redis_mock: MagicMock, limiter: RateLimiter) -> None:
    """Reset timestamp is in the future."""
    redis_mock.zremrangebyscore = AsyncMock()
    redis_mock.zcard = AsyncMock(return_value=0)
    _setup_pipeline(redis_mock)

    now = time.time()
    _, info = await limiter.check("127.0.0.1")

    assert info["reset"] > int(now)
    assert info["reset"] <= int(now) + 60


@pytest.mark.asyncio
async def test_different_identifiers_independent(
    redis_mock: MagicMock, limiter: RateLimiter
) -> None:
    """Different identifiers have independent counters."""
    # First id: at limit → blocked
    # Second id: under limit → allowed

    async def zcard_side_effect(key: str) -> int:
        return 3 if "127.0.0.1" in key else 0

    redis_mock.zremrangebyscore = AsyncMock()
    redis_mock.zcard = AsyncMock(side_effect=zcard_side_effect)
    _setup_pipeline(redis_mock)

    allowed1, _ = await limiter.check("127.0.0.1")
    allowed2, _ = await limiter.check("10.0.0.1")

    assert allowed1 is False
    assert allowed2 is True


@pytest.mark.asyncio
async def test_default_limit_from_settings() -> None:
    """RateLimiter picks up default settings when no args given."""
    redis_mock = MagicMock()
    redis_mock.zremrangebyscore = AsyncMock()
    redis_mock.zcard = AsyncMock(return_value=0)
    _setup_pipeline(redis_mock)

    limiter = RateLimiter(redis_client=redis_mock)
    assert limiter.limit == 10
    assert limiter.window == 60

    allowed, _ = await limiter.check("test")
    assert allowed is True
