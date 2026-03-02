"""Tests for token bucket rate limiter."""

import asyncio
import time

import pytest

from skopaq.broker.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_acquire_within_limit():
    """Acquiring within limit should not block."""
    limiter = RateLimiter(max_calls=10, period=1.0)
    start = time.monotonic()
    for _ in range(10):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    # Should complete almost instantly
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_acquire_exceeding_limit_sleeps():
    """Exceeding limit should cause a brief sleep."""
    limiter = RateLimiter(max_calls=2, period=1.0)
    # Use up all tokens
    await limiter.acquire()
    await limiter.acquire()
    # Third call should sleep
    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed > 0.1  # Should have waited


@pytest.mark.asyncio
async def test_tokens_refill_over_time():
    """Tokens should refill after waiting."""
    limiter = RateLimiter(max_calls=1, period=0.1)
    await limiter.acquire()
    # Wait for refill
    await asyncio.sleep(0.15)
    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    # Should not block since token was refilled
    assert elapsed < 0.1
