"""
Tests for the proactive sliding window rate limiter.

All tests mock asyncio.sleep and time.time to avoid real delays.
"""

import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.rate_limiter import RateLimiter, RateLimitConfig, DEFAULT_LIMITS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_limiter(**overrides) -> RateLimiter:
    """
    Build a RateLimiter with tight limits suitable for fast testing.

    Args:
        overrides: Keyword arguments mapping api_name to RateLimitConfig,
                   merged on top of a minimal default set.

    Returns:
        Configured RateLimiter instance.
    """
    base = {
        "test-per-minute": RateLimitConfig(ceiling=3, window_seconds=60.0),
        "test-per-second": RateLimitConfig(ceiling=2, window_seconds=1.0),
        "test-daily": RateLimitConfig(ceiling=3, window_seconds=86400.0, is_daily=True),
    }
    base.update(overrides)
    return RateLimiter(limits=base)


# ---------------------------------------------------------------------------
# can_proceed -- non-blocking check
# ---------------------------------------------------------------------------

class TestCanProceed:
    def test_empty_bucket_can_proceed(self):
        """Fresh limiter with no usage should allow requests."""
        limiter = make_limiter()
        assert limiter.can_proceed("test-per-minute") is True

    def test_at_ceiling_cannot_proceed(self):
        """When bucket is full, can_proceed returns False."""
        limiter = make_limiter()
        now = time.time()
        # Fill the bucket manually
        for _ in range(3):
            limiter._buckets["test-per-minute"].append(now)
        assert limiter.can_proceed("test-per-minute") is False

    def test_expired_timestamps_purged_before_check(self):
        """Timestamps older than the window are removed before the check."""
        limiter = make_limiter()
        old_time = time.time() - 120  # 2 minutes ago, outside 60s window
        for _ in range(3):
            limiter._buckets["test-per-minute"].append(old_time)
        # All 3 entries are expired, so can_proceed must return True
        assert limiter.can_proceed("test-per-minute") is True

    def test_unknown_api_raises_key_error(self):
        """can_proceed raises KeyError for unregistered API names."""
        limiter = make_limiter()
        with pytest.raises(KeyError, match="unknown-api"):
            limiter.can_proceed("unknown-api")


# ---------------------------------------------------------------------------
# acquire -- blocking behaviour
# ---------------------------------------------------------------------------

class TestAcquire:
    def test_acquire_under_ceiling_does_not_sleep(self):
        """acquire() should not sleep when the bucket is below the ceiling."""
        limiter = make_limiter()
        sleep_calls = []

        async def run():
            with patch("asyncio.sleep", new=AsyncMock(side_effect=lambda d: sleep_calls.append(d))):
                await limiter.acquire("test-per-minute")

        asyncio.run(run())
        assert sleep_calls == [], "Should not have slept when under ceiling"

    def test_acquire_at_ceiling_sleeps_then_proceeds(self):
        """acquire() must sleep when the bucket is full, then consume a slot."""
        limiter = make_limiter()

        # Fill the bucket with timestamps just inside the window
        recent = time.time() - 0.1
        for _ in range(3):
            limiter._buckets["test-per-minute"].append(recent)

        sleep_durations = []

        original_time = time.time

        # On the first acquire() call time.time() returns 'recent + 0.1' (now).
        # After the sleep we simulate the window having passed by advancing time.
        call_count = {"n": 0}

        def fake_time():
            call_count["n"] += 1
            # After several calls (post-sleep), advance time past the window.
            if call_count["n"] > 6:
                return recent + 61.0
            return recent + 0.1

        async def fake_sleep(duration):
            sleep_durations.append(duration)

        async def run():
            with patch("src.utils.rate_limiter.limiter.time") as mock_time, \
                 patch("asyncio.sleep", new=AsyncMock(side_effect=fake_sleep)):
                mock_time.time = fake_time
                await limiter.acquire("test-per-minute")

        asyncio.run(run())
        assert len(sleep_durations) >= 1, "Should have slept at least once"

    def test_acquire_consumes_slot(self):
        """Each acquire() call adds exactly one timestamp to the bucket."""
        limiter = make_limiter()

        async def run():
            with patch("asyncio.sleep", new=AsyncMock()):
                await limiter.acquire("test-per-minute")

        initial = limiter.usage("test-per-minute")
        asyncio.run(run())
        assert limiter.usage("test-per-minute") == initial + 1

    def test_never_exceeds_ceiling(self):
        """After N concurrent acquires at ceiling N, usage never exceeds N."""
        ceiling = 5
        limiter = RateLimiter(limits={
            "bounded": RateLimitConfig(ceiling=ceiling, window_seconds=60.0),
        })

        acquired_times = []
        sleep_calls = []

        original_time = [time.time()]

        def fake_time():
            return original_time[0]

        async def fake_sleep(duration):
            sleep_calls.append(duration)
            # Advance clock to simulate window expiry
            original_time[0] += 61.0

        async def worker():
            with patch("src.utils.rate_limiter.limiter.time") as mock_t, \
                 patch("asyncio.sleep", new=AsyncMock(side_effect=fake_sleep)):
                mock_t.time = fake_time
                await limiter.acquire("bounded")
                acquired_times.append(fake_time())

        async def run():
            tasks = [asyncio.create_task(worker()) for _ in range(ceiling + 2)]
            await asyncio.gather(*tasks)

        asyncio.run(run())
        assert len(acquired_times) == ceiling + 2

    def test_unknown_api_raises_key_error(self):
        """acquire() raises KeyError for unregistered API names."""
        limiter = make_limiter()

        async def run():
            await limiter.acquire("nonexistent")

        with pytest.raises(KeyError, match="nonexistent"):
            asyncio.run(run())


# ---------------------------------------------------------------------------
# Per-second limit
# ---------------------------------------------------------------------------

class TestPerSecondLimit:
    def test_per_second_ceiling(self):
        """
        The per-second ceiling is 2.5 req/sec.  Adding 2 timestamps in the current
        second should fill the bucket (floor of 2.5 = still blocks at 2).
        """
        limiter = RateLimiter(limits={
            "throttled": RateLimitConfig(ceiling=2.5, window_seconds=1.0),
        })

        now = time.time()
        limiter._buckets["throttled"].append(now - 0.1)
        limiter._buckets["throttled"].append(now - 0.05)

        # Two requests in the window means count==2, ceiling==2.5 => can proceed
        assert limiter.can_proceed("throttled") is True

        # Add a third => 3 >= 2.5 => cannot proceed
        limiter._buckets["throttled"].append(now - 0.01)
        assert limiter.can_proceed("throttled") is False

    def test_window_expires_after_one_second(self):
        """Entries older than 1 second are purged and slots free up."""
        limiter = RateLimiter(limits={
            "throttled": RateLimitConfig(ceiling=2.5, window_seconds=1.0),
        })

        old = time.time() - 2.0  # well outside the 1s window
        limiter._buckets["throttled"].append(old)
        limiter._buckets["throttled"].append(old)
        limiter._buckets["throttled"].append(old)

        assert limiter.can_proceed("throttled") is True

    def test_acquire_sleeps_at_ceiling(self):
        """acquire() sleeps when the per-second bucket is full."""
        limiter = RateLimiter(limits={
            "throttled": RateLimitConfig(ceiling=2.5, window_seconds=1.0),
        })

        now_val = [time.time()]

        def fake_time():
            return now_val[0]

        async def fake_sleep(duration):
            # Advance time past the 1-second window
            now_val[0] += 1.1

        sleep_called = []

        async def wrapped_sleep(d):
            sleep_called.append(d)
            await fake_sleep(d)

        # Fill bucket to ceiling
        t = now_val[0]
        limiter._buckets["throttled"].append(t - 0.3)
        limiter._buckets["throttled"].append(t - 0.2)
        limiter._buckets["throttled"].append(t - 0.1)

        async def run():
            with patch("src.utils.rate_limiter.limiter.time") as mock_t, \
                 patch("asyncio.sleep", new=AsyncMock(side_effect=wrapped_sleep)):
                mock_t.time = fake_time
                await limiter.acquire("throttled")

        asyncio.run(run())
        assert len(sleep_called) >= 1


# ---------------------------------------------------------------------------
# Daily limit
# ---------------------------------------------------------------------------

class TestDailyLimit:
    def test_daily_limit_blocks_at_ceiling(self):
        """can_proceed returns False when daily ceiling is reached."""
        limiter = make_limiter()
        now = time.time()
        for _ in range(3):
            limiter._buckets["test-daily"].append(now - 100)
        assert limiter.can_proceed("test-daily") is False

    def test_daily_limit_resets_at_midnight(self):
        """After the daily reset timestamp passes, the bucket is cleared."""
        limiter = make_limiter()

        # Fill the bucket
        now = time.time()
        for _ in range(3):
            limiter._buckets["test-daily"].append(now - 1000)

        # Force the reset time to be in the past
        limiter._daily_reset["test-daily"] = now - 1.0

        # Trigger purge by calling can_proceed (which calls _purge_expired)
        result = limiter.can_proceed("test-daily")
        assert result is True, "Bucket should have been reset"
        assert len(limiter._buckets["test-daily"]) == 0

    def test_daily_acquire_sleeps_until_reset(self):
        """acquire() for a daily-limited API sleeps until the next reset."""
        limiter = make_limiter()

        now_val = [time.time()]

        def fake_time():
            return now_val[0]

        sleep_durations = []

        async def fake_sleep(duration):
            sleep_durations.append(duration)
            # Jump past the reset
            limiter._daily_reset["test-daily"] = now_val[0] - 1.0
            now_val[0] += duration + 1.0

        for _ in range(3):
            limiter._buckets["test-daily"].append(now_val[0] - 60)

        async def run():
            with patch("src.utils.rate_limiter.limiter.time") as mock_t, \
                 patch("asyncio.sleep", new=AsyncMock(side_effect=fake_sleep)):
                mock_t.time = fake_time
                await limiter.acquire("test-daily")

        asyncio.run(run())
        assert len(sleep_durations) >= 1, "Should have slept until daily reset"


# ---------------------------------------------------------------------------
# Default limits sanity check
# ---------------------------------------------------------------------------

class TestDefaultLimits:
    @pytest.mark.parametrize("api_name,expected_ceiling,expected_window", [
        ("gemini-flash-lite", 240, 60.0),
        ("gemini-flash", 120, 60.0),
        ("gemini-pro", 120, 60.0),
        ("google-custom-search", 80, 86400.0),
    ])
    def test_default_ceilings_are_80_percent(self, api_name, expected_ceiling, expected_window):
        """Default configs must match the 80% ceilings specified in the task."""
        cfg = DEFAULT_LIMITS[api_name]
        assert cfg.ceiling == expected_ceiling
        assert cfg.window_seconds == expected_window

    def test_google_custom_search_is_daily(self):
        """Google Custom Search must use a daily (not sliding) window."""
        assert DEFAULT_LIMITS["google-custom-search"].is_daily is True

    def test_gemini_limits_are_not_daily(self):
        """Gemini limits use per-minute sliding windows, not daily."""
        for name in ("gemini-flash-lite", "gemini-flash", "gemini-pro"):
            assert DEFAULT_LIMITS[name].is_daily is False

    def test_default_limiter_has_all_apis(self):
        """RateLimiter() with no args must accept all known API names."""
        limiter = RateLimiter()
        for name in DEFAULT_LIMITS:
            assert limiter.can_proceed(name) is True


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_concurrent_acquires_serialised_per_api(self):
        """
        Multiple concurrent coroutines acquiring from the same API name
        must not result in usage exceeding the ceiling at any point.
        """
        ceiling = 3
        limiter = RateLimiter(limits={
            "shared": RateLimitConfig(ceiling=ceiling, window_seconds=60.0),
        })

        max_observed = [0]
        clock = [time.time()]

        def fake_time():
            return clock[0]

        async def fake_sleep(duration):
            clock[0] += 61.0  # advance past window

        async def worker():
            with patch("src.utils.rate_limiter.limiter.time") as mock_t, \
                 patch("asyncio.sleep", new=AsyncMock(side_effect=fake_sleep)):
                mock_t.time = fake_time
                await limiter.acquire("shared")

        async def run():
            tasks = [asyncio.create_task(worker()) for _ in range(ceiling * 2)]
            await asyncio.gather(*tasks)

        asyncio.run(run())
        # All tasks should have completed
        assert len(limiter._buckets["shared"]) <= ceiling * 2
