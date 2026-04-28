"""
Rate limiter package -- proactive sliding-window enforcement for API calls.

Public API: RateLimiter, RateLimitConfig, DEFAULT_LIMITS, QuotaExhaustedError.
"""

from src.utils.rate_limiter.config import (
    DEFAULT_LIMITS,
    QuotaExhaustedError,
    RateLimitConfig,
)
from src.utils.rate_limiter.limiter import RateLimiter

__all__ = [
    "DEFAULT_LIMITS",
    "QuotaExhaustedError",
    "RateLimitConfig",
    "RateLimiter",
]
