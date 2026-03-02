"""Token bucket rate limiter for INDstocks API calls."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token bucket rate limiter.

    Enforces a maximum number of calls per second.  Callers ``await acquire()``
    before each API call — it will sleep if the bucket is empty.
    """

    def __init__(self, max_calls: float, period: float = 1.0) -> None:
        self.max_calls = max_calls
        self.period = period
        self._tokens = max_calls
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        async with self._lock:
            self._refill()
            if self._tokens < 1:
                wait_time = (1 - self._tokens) * (self.period / self.max_calls)
                await asyncio.sleep(wait_time)
                self._refill()
            self._tokens -= 1

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.max_calls, self._tokens + elapsed * (self.max_calls / self.period))
        self._last_refill = now
