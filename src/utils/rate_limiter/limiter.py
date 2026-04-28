"""
RateLimiter -- asyncio-safe proactive sliding window rate limiter.

Tracks API usage per API/model name and blocks calls before they
would exceed configured ceilings. Never relies on 429 backoff -- all
limits are enforced before the call is made.
"""

import asyncio
import logging
import time
from collections import deque
from typing import Dict

from src.utils.rate_limiter.config import (
    DEFAULT_LIMITS,
    QuotaExhaustedError,
    RateLimitConfig,
    pacific_midnight_tomorrow,
)

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Asyncio-safe proactive sliding window rate limiter.

    Maintains a deque of timestamps per API name. Before each call,
    expired timestamps are purged and the count is checked against the
    ceiling. If the ceiling is reached, the limiter blocks (via
    asyncio.sleep) until a slot opens.

    For daily limits (is_daily=True), the limiter resets at midnight
    Pacific Time rather than using a true sliding window.

    Multiple coroutines may call acquire() concurrently. An asyncio.Lock
    per API name serialises access to each bucket to prevent races.
    """

    def __init__(self, limits: Dict[str, RateLimitConfig] | None = None) -> None:
        self._limits: Dict[str, RateLimitConfig] = (
            limits if limits is not None else DEFAULT_LIMITS
        )
        self._buckets: Dict[str, deque] = {name: deque() for name in self._limits}
        self._locks: Dict[str, asyncio.Lock] = {
            name: asyncio.Lock() for name in self._limits
        }
        self._daily_reset: Dict[str, float] = {
            name: pacific_midnight_tomorrow()
            for name, cfg in self._limits.items()
            if cfg.is_daily or cfg.daily_ceiling is not None
        }
        self._daily_buckets: Dict[str, deque] = {
            name: deque()
            for name, cfg in self._limits.items()
            if cfg.daily_ceiling is not None
        }
        self._lockouts: Dict[str, float] = {}

    def _purge_expired(self, api_name: str, now: float) -> None:
        """Remove expired timestamps from sliding and daily buckets."""
        cfg = self._limits[api_name]
        bucket = self._buckets[api_name]

        if cfg.is_daily:
            reset_time = self._daily_reset[api_name]
            if now >= reset_time:
                bucket.clear()
                self._daily_reset[api_name] = pacific_midnight_tomorrow()
        else:
            cutoff = now - cfg.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

        if cfg.daily_ceiling is not None:
            daily_reset = self._daily_reset.get(api_name)
            if daily_reset is not None and now >= daily_reset:
                self._daily_buckets[api_name].clear()
                self._daily_reset[api_name] = pacific_midnight_tomorrow()
                if api_name in self._lockouts and self._lockouts[api_name] <= now:
                    self._lockouts.pop(api_name, None)

    def can_proceed(self, api_name: str) -> bool:
        """Non-blocking advisory check. Does NOT consume a slot."""
        if api_name not in self._limits:
            raise KeyError(
                f"Unknown API: {api_name!r}. Known APIs: {list(self._limits)}"
            )

        now = time.time()
        cfg = self._limits[api_name]
        if self._lockouts.get(api_name, 0.0) > now:
            return False
        self._purge_expired(api_name, now)
        if len(self._buckets[api_name]) >= cfg.ceiling:
            return False
        if cfg.daily_ceiling is not None:
            if len(self._daily_buckets[api_name]) >= cfg.daily_ceiling:
                return False
        return True

    async def acquire(self, api_name: str) -> None:
        """Block until a request slot is available, then consume it."""
        if api_name not in self._limits:
            raise KeyError(
                f"Unknown API: {api_name!r}. Known APIs: {list(self._limits)}"
            )

        async with self._locks[api_name]:
            cfg = self._limits[api_name]
            bucket = self._buckets[api_name]

            now = time.time()
            lockout_until = self._lockouts.get(api_name, 0.0)
            if lockout_until > now:
                wait = lockout_until - now
                raise QuotaExhaustedError(
                    f"{api_name} daily quota exhausted; locked out for {wait:.0f}s "
                    f"until midnight Pacific reset"
                )

            while True:
                now = time.time()
                self._purge_expired(api_name, now)
                count = len(bucket)

                if cfg.daily_ceiling is not None:
                    daily_count = len(self._daily_buckets[api_name])
                    if daily_count >= cfg.daily_ceiling:
                        reset_time = self._daily_reset[api_name]
                        wait = max(0.0, reset_time - now)
                        raise QuotaExhaustedError(
                            f"{api_name} daily ceiling reached "
                            f"({daily_count}/{cfg.daily_ceiling}); "
                            f"{wait:.0f}s until midnight Pacific reset"
                        )

                if count < cfg.ceiling:
                    break

                if cfg.is_daily:
                    reset_time = self._daily_reset[api_name]
                    wait = max(0.0, reset_time - now)
                    logger.warning(
                        "Rate limiter: %s daily limit reached (%d/%d). "
                        "Sleeping %.1fs until midnight Pacific reset.",
                        api_name, count, int(cfg.ceiling), wait,
                    )
                else:
                    oldest = bucket[0]
                    wait = max(0.0, (oldest + cfg.window_seconds) - now) + 0.001
                    logger.debug(
                        "Rate limiter: %s at ceiling (%d/%d). Sleeping %.3fs.",
                        api_name, count, int(cfg.ceiling), wait,
                    )

                await asyncio.sleep(wait)

            stamp = time.time()
            bucket.append(stamp)
            if cfg.daily_ceiling is not None:
                self._daily_buckets[api_name].append(stamp)

            current_count = len(bucket)
            utilisation = current_count / cfg.ceiling

            if utilisation >= 0.9:
                logger.warning(
                    "Rate limiter: %s utilisation at %.0f%% of ceiling (%d/%d).",
                    api_name, utilisation * 100, current_count, int(cfg.ceiling),
                )

            if cfg.daily_ceiling is not None:
                daily_count = len(self._daily_buckets[api_name])
                if daily_count >= cfg.daily_ceiling * 0.9:
                    logger.warning(
                        "Rate limiter: %s daily utilisation at %d/%d.",
                        api_name, daily_count, cfg.daily_ceiling,
                    )

    def set_lockout(self, api_name: str, until: float | None = None) -> None:
        """Lock out further acquire() calls for an API until the given timestamp."""
        if api_name not in self._limits:
            raise KeyError(
                f"Unknown API: {api_name!r}. Known APIs: {list(self._limits)}"
            )
        if until is None:
            until = pacific_midnight_tomorrow()
        self._lockouts[api_name] = until
        remaining = max(0.0, until - time.time())
        logger.warning(
            "Rate limiter: locking out %s for %.0fs (until daily quota reset).",
            api_name, remaining,
        )

    def usage(self, api_name: str) -> int:
        """Return the current number of requests recorded in the active window."""
        if api_name not in self._limits:
            raise KeyError(
                f"Unknown API: {api_name!r}. Known APIs: {list(self._limits)}"
            )

        now = time.time()
        self._purge_expired(api_name, now)
        return len(self._buckets[api_name])
