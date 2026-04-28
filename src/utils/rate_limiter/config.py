"""
Configuration types and defaults for the rate limiter.

Defines RateLimitConfig (per-API config dataclass), the
QuotaExhaustedError exception, default per-API limits tuned for the
Gemini free tier, and the Pacific midnight reset helper used by daily
windows.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict


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
}


def pacific_midnight_tomorrow() -> float:
    """
    Return the Unix timestamp for the next midnight Pacific Time (UTC-8).
    """
    pacific_offset = timedelta(hours=_PACIFIC_UTC_OFFSET)
    now_pacific = datetime.now(timezone.utc) + pacific_offset
    tomorrow_pacific = (now_pacific + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    midnight_utc = tomorrow_pacific - pacific_offset
    return midnight_utc.timestamp()
