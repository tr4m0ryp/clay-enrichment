"""
Sender pool with round-robin rotation and daily per-sender limits.

Tracks send counts per sender, auto-resets at midnight, and selects
the sender with the lowest daily count that is still under limit.
"""

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, date

from src.config import SenderAccount

logger = logging.getLogger(__name__)

_BUSINESS_HOUR_START = 8
_BUSINESS_HOUR_END = 18


def is_business_hours() -> bool:
    """
    Check whether the current local time is within business hours.

    Business hours are defined as 8:00 to 18:00 local time,
    Monday through Friday.

    Returns:
        True if currently within business hours, False otherwise.
    """
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return _BUSINESS_HOUR_START <= now.hour < _BUSINESS_HOUR_END


def compute_delay(min_delay: int, max_delay: int) -> float:
    """
    Compute a randomized delay with +/- 20% jitter.

    Args:
        min_delay: Minimum delay in seconds.
        max_delay: Maximum delay in seconds.

    Returns:
        A randomized delay value in seconds.
    """
    base = random.uniform(min_delay, max_delay)
    jitter = base * random.uniform(-0.20, 0.20)
    return max(0.0, base + jitter)




@dataclass
class _SenderState:
    """Tracks daily send count for a single sender account."""

    account: SenderAccount
    daily_count: int = 0
    last_reset_date: date = field(default_factory=date.today)


class SenderPool:
    """
    Manages a pool of sender accounts with daily limits and rotation.

    Selects the sender with the lowest daily count (round-robin weighted
    by remaining capacity). Resets counts at midnight automatically.
    """

    def __init__(self, senders: list[SenderAccount], daily_limit: int) -> None:
        """
        Initialise the sender pool.

        Args:
            senders: List of configured sender accounts.
            daily_limit: Maximum emails per sender per day.
        """
        self._states = [_SenderState(account=s) for s in senders]
        self._daily_limit = daily_limit

    @property
    def daily_limit(self) -> int:
        """Return the configured daily limit per sender."""
        return self._daily_limit

    def _maybe_reset(self) -> None:
        """Reset daily counts if the date has changed since last reset."""
        today = date.today()
        for state in self._states:
            if state.last_reset_date != today:
                state.daily_count = 0
                state.last_reset_date = today

    def next_sender(self) -> SenderAccount | None:
        """
        Return the sender with the lowest daily count that is under limit.

        Automatically resets counts at midnight.

        Returns:
            The next SenderAccount to use, or None if all are exhausted.
        """
        if not self._states:
            return None

        self._maybe_reset()

        available = [
            s for s in self._states if s.daily_count < self._daily_limit
        ]
        if not available:
            return None

        best = min(available, key=lambda s: s.daily_count)
        return best.account

    def record_send(self, email: str) -> None:
        """
        Increment the daily count for the sender that matches the email.

        Args:
            email: The sender email address that was used.
        """
        for state in self._states:
            if state.account.email == email:
                state.daily_count += 1
                return

    def reset_daily(self) -> None:
        """Force-reset all daily counts (useful for testing)."""
        today = date.today()
        for state in self._states:
            state.daily_count = 0
            state.last_reset_date = today

    def get_count(self, email: str) -> int:
        """
        Return the current daily count for a sender.

        Args:
            email: The sender email address.

        Returns:
            The number of emails sent today by this sender.
        """
        for state in self._states:
            if state.account.email == email:
                return state.daily_count
        return 0
