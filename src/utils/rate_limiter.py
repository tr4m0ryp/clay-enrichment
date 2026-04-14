"""
Proactive sliding window rate limiter.

Tracks API usage per API/model name and blocks calls before they would
exceed configured ceilings. Never relies on 429 backoff -- all limits
are enforced before the call is made.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict

logger = logging.getLogger(__name__)

# Pacific Time offset (UTC-8 standard, UTC-7 daylight)
# We use a fixed offset of UTC-8 for midnight reset simplicity.
_PACIFIC_UTC_OFFSET = -8


@dataclass
class RateLimitConfig:
    """
    Configuration for a single API's rate limit.

    Attributes:
        ceiling: Maximum requests allowed within the window (already at 80%).
        window_seconds: The sliding window duration in seconds.
        is_daily: If True, the window resets at midnight Pacific Time instead
                  of using a sliding window.
        daily_ceiling: Optional additional per-day cap applied on top of the
                       per-window ceiling. Resets at midnight Pacific.
    """

    ceiling: float
    window_seconds: float
    is_daily: bool = False
    daily_ceiling: int | None = None


class QuotaExhaustedError(Exception):
    """Raised when an API's daily quota is exhausted and cannot be retried soon."""


# Default limits tuned for Gemini API free tier (with headroom).
# Free tier stated quotas (per project, per model, per day):
#   gemini-2.5-flash-lite: 15 RPM / 1000 RPD (20 RPD observed on this key)
#   gemini-2.5-flash:      10 RPM / 250 RPD
#   gemini-2.5-pro:         5 RPM / 100 RPD
# Set daily_ceiling well below stated RPD to avoid hitting 429s locally; the
# quota-exhaustion detection in GeminiClient will clamp tighter if actual
# quota is lower than configured.
DEFAULT_LIMITS: Dict[str, RateLimitConfig] = {
    # Gemini models -- keys match the model names in .env config
    "gemini-2.5-flash-lite": RateLimitConfig(
        ceiling=12, window_seconds=60.0, daily_ceiling=800,
    ),
    "gemini-2.5-flash": RateLimitConfig(
        ceiling=8, window_seconds=60.0, daily_ceiling=200,
    ),
    "gemini-2.5-pro": RateLimitConfig(
        ceiling=4, window_seconds=60.0, daily_ceiling=80,
    ),
    # Legacy short names (for backward compat with tests)
    "gemini-flash-lite": RateLimitConfig(ceiling=240, window_seconds=60.0),
    "gemini-flash": RateLimitConfig(ceiling=120, window_seconds=60.0),
    "gemini-pro": RateLimitConfig(ceiling=120, window_seconds=60.0),
    "google-custom-search": RateLimitConfig(ceiling=80, window_seconds=86400.0, is_daily=True),
    "google_search": RateLimitConfig(ceiling=80, window_seconds=86400.0, is_daily=True),
    "notion": RateLimitConfig(ceiling=2.5, window_seconds=1.0),
}


def _pacific_midnight_tomorrow() -> float:
    """
    Return the Unix timestamp for the next midnight Pacific Time (UTC-8).

    Returns:
        Unix timestamp (float) for midnight Pacific Time tomorrow.
    """
    pacific_offset = timedelta(hours=_PACIFIC_UTC_OFFSET)
    now_pacific = datetime.now(timezone.utc) + pacific_offset
    tomorrow_pacific = (now_pacific + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # Convert back to UTC unix timestamp
    midnight_utc = tomorrow_pacific - pacific_offset
    return midnight_utc.timestamp()


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
        """
        Initialise the rate limiter with the given limit configurations.

        Args:
            limits: Mapping of API name to RateLimitConfig. Defaults to
                    DEFAULT_LIMITS if not provided.
        """
        self._limits: Dict[str, RateLimitConfig] = limits if limits is not None else DEFAULT_LIMITS
        self._buckets: Dict[str, deque] = {name: deque() for name in self._limits}
        self._locks: Dict[str, asyncio.Lock] = {name: asyncio.Lock() for name in self._limits}
        # For daily limits (is_daily OR daily_ceiling): track the reset timestamp
        self._daily_reset: Dict[str, float] = {
            name: _pacific_midnight_tomorrow()
            for name, cfg in self._limits.items()
            if cfg.is_daily or cfg.daily_ceiling is not None
        }
        # Separate bucket for daily_ceiling tracking (when paired with per-window ceiling).
        self._daily_buckets: Dict[str, deque] = {
            name: deque()
            for name, cfg in self._limits.items()
            if cfg.daily_ceiling is not None
        }
        # Hard lockouts: acquire() raises QuotaExhaustedError until this timestamp.
        self._lockouts: Dict[str, float] = {}

    def _purge_expired(self, api_name: str, now: float) -> None:
        """
        Remove timestamps outside the current sliding window from the bucket.

        For daily limits, clears the entire bucket if the reset time has passed.
        For configs with daily_ceiling, also clears the daily bucket at reset.

        Args:
            api_name: The API identifier whose bucket to purge.
            now: Current Unix timestamp.
        """
        cfg = self._limits[api_name]
        bucket = self._buckets[api_name]

        if cfg.is_daily:
            reset_time = self._daily_reset[api_name]
            if now >= reset_time:
                bucket.clear()
                self._daily_reset[api_name] = _pacific_midnight_tomorrow()
        else:
            cutoff = now - cfg.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

        # Purge secondary daily bucket if configured.
        if cfg.daily_ceiling is not None:
            daily_reset = self._daily_reset.get(api_name)
            if daily_reset is not None and now >= daily_reset:
                self._daily_buckets[api_name].clear()
                self._daily_reset[api_name] = _pacific_midnight_tomorrow()
                # Clear any stale lockout when the daily window resets.
                if api_name in self._lockouts and self._lockouts[api_name] <= now:
                    self._lockouts.pop(api_name, None)

    def can_proceed(self, api_name: str) -> bool:
        """
        Non-blocking check whether a request can be made right now.

        This does NOT consume a slot. It is advisory only. Use acquire()
        before making the actual API call.

        Args:
            api_name: The API identifier to check.

        Returns:
            True if a request can proceed without exceeding the ceiling,
            False otherwise.

        Raises:
            KeyError: If api_name is not in the configured limits.
        """
        if api_name not in self._limits:
            raise KeyError(f"Unknown API: {api_name!r}. Known APIs: {list(self._limits)}")

        now = time.time()
        cfg = self._limits[api_name]
        # Hard lockout from prior quota exhaustion.
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
        """
        Block until a request slot is available, then consume it.

        Safe for concurrent use by multiple coroutines. Each api_name has
        its own lock to prevent races on the shared bucket.

        Logs a warning if utilisation exceeds 90% of the ceiling after
        the slot is acquired.

        Args:
            api_name: The API identifier to acquire a slot for.

        Raises:
            KeyError: If api_name is not in the configured limits.
        """
        if api_name not in self._limits:
            raise KeyError(f"Unknown API: {api_name!r}. Known APIs: {list(self._limits)}")

        async with self._locks[api_name]:
            cfg = self._limits[api_name]
            bucket = self._buckets[api_name]

            # Fail fast if this API is locked out from a prior 429 daily exhaustion.
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

                # Check daily_ceiling first -- if exhausted, this will be a long wait,
                # so raise instead of blocking the caller for hours.
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

                # Calculate how long until the oldest slot expires.
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

            # Consume the slot (both per-window and daily trackers).
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
        """
        Lock out further acquire() calls for an API until the given timestamp.

        Called by the Gemini client when it observes a 429 RESOURCE_EXHAUSTED
        response, so subsequent calls fail fast rather than hammering the API.

        Args:
            api_name: The API identifier to lock out.
            until: Unix timestamp when the lockout expires. Defaults to
                   midnight Pacific (next daily quota reset).
        """
        if api_name not in self._limits:
            raise KeyError(f"Unknown API: {api_name!r}. Known APIs: {list(self._limits)}")
        if until is None:
            until = _pacific_midnight_tomorrow()
        self._lockouts[api_name] = until
        remaining = max(0.0, until - time.time())
        logger.warning(
            "Rate limiter: locking out %s for %.0fs (until daily quota reset).",
            api_name, remaining,
        )

    def usage(self, api_name: str) -> int:
        """
        Return the current number of requests recorded in the active window.

        Args:
            api_name: The API identifier to query.

        Returns:
            Number of requests in the current window.

        Raises:
            KeyError: If api_name is not in the configured limits.
        """
        if api_name not in self._limits:
            raise KeyError(f"Unknown API: {api_name!r}. Known APIs: {list(self._limits)}")

        now = time.time()
        self._purge_expired(api_name, now)
        return len(self._buckets[api_name])
