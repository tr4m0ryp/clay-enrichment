import asyncio
import time
from collections import defaultdict

from src.utils.logger import get_logger

_logger = get_logger("rate_limiter")

# Minimum interval in seconds between calls per api_name
_DEFAULT_INTERVALS: dict[str, float] = {
    "google_search": 1.0,
}


class RateLimiter:
    """Simple token-bucket-style rate limiter keyed by api_name."""

    def __init__(self, intervals: dict[str, float] | None = None) -> None:
        self._intervals = intervals or _DEFAULT_INTERVALS
        self._last_call: dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def acquire(self, api_name: str) -> None:
        interval = self._intervals.get(api_name, 0.0)
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call[api_name]
            wait = interval - elapsed
            if wait > 0:
                _logger.debug("rate_limiter: %s waiting %.2fs", api_name, wait)
                await asyncio.sleep(wait)
            self._last_call[api_name] = time.monotonic()
