"""In-memory GitHub PAT pool with rate-limit-aware rotation.

Holds the active rows of `github_tokens` in memory, hands out the highest
`rate_limit_remaining` token to the scraper, and rotates on 429/403 or
proactively when remaining drops below 10. Rate-limit marks and success
counters persist back to Supabase via inline SQL.

Ports FrogBytes_V3/lib/api-keys/github-token-manager.ts behaviourally
(see notes/gemini-scraper-supabase-db-refactor.md lines 448-518). The
Python port is a single-process pool guarded by an `asyncio.Lock`; no
inter-process synchronization is required.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg

from src.api_keys.types import GitHubToken
from src.utils.logger import get_logger


logger = get_logger(__name__)


# Refresh the in-memory pool whenever it has been older than this (seconds).
_REFRESH_INTERVAL_SECONDS: float = 120.0

# Default rate-limit reset window when the GitHub response did not include
# X-RateLimit-Reset (most 429/403 responses do, but be defensive).
_DEFAULT_RATE_LIMIT_BACKOFF = timedelta(hours=1)


_REFRESH_SQL = """
SELECT id, token_name, token_value, rate_limit_remaining, rate_limit_reset_at
FROM github_tokens
WHERE is_active = true
  AND (rate_limit_reset_at IS NULL OR rate_limit_reset_at < now())
ORDER BY rate_limit_remaining DESC NULLS FIRST;
"""

_MARK_RATE_LIMITED_SQL = """
UPDATE github_tokens
SET rate_limit_remaining = 0,
    rate_limit_reset_at = $1,
    failed_requests = failed_requests + 1
WHERE id = $2;
"""

_MARK_SUCCESS_SQL = """
UPDATE github_tokens
SET rate_limit_remaining = $1,
    rate_limit_reset_at = $2,
    successful_requests = successful_requests + 1
WHERE id = $3;
"""


class GitHubTokenPool:
    """Single-process pool of GitHub PATs sourced from `github_tokens`.

    The pool keeps a sorted list of active, non-rate-limited tokens in
    memory. `get_current_token` returns the highest-remaining token,
    refreshing from Supabase when the cache is empty or older than
    `_REFRESH_INTERVAL_SECONDS`. The scraper calls `mark_success` after
    every API call to record the current rate-limit headers, and either
    `mark_current_rate_limited` (on 429/403) or `rotate_to_next` (on a
    proactive low-remaining check) to advance the pointer.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool: asyncpg.Pool = pool
        self._available: list[GitHubToken] = []
        self._index: int = 0
        self._last_refresh: float = 0.0
        self._rotation_attempts: int = 0
        self._refresh_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_current_token(self) -> Optional[str]:
        """Return the current PAT string, or None if no tokens are available.

        Triggers a refresh when the cache is empty or stale (older than
        `_REFRESH_INTERVAL_SECONDS`). Callers receiving None should sleep
        and retry; persistent emptiness signals "all tokens rate-limited".
        """
        if self._needs_refresh():
            await self.refresh_tokens()
        async with self._refresh_lock:
            if not self._available:
                return None
            if self._index >= len(self._available):
                self._index = 0
            token = self._available[self._index]
            return token.token_value

    async def refresh_tokens(self) -> None:
        """Reload the in-memory pool from `github_tokens`.

        Runs the SELECT under `_refresh_lock` so concurrent callers do
        not double-fetch. Resets `_index` and `_rotation_attempts` and
        stamps `_last_refresh`.
        """
        async with self._refresh_lock:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(_REFRESH_SQL)
            self._available = [
                GitHubToken(
                    id=row["id"],
                    token_name=row["token_name"],
                    token_value=row["token_value"],
                    rate_limit_remaining=row["rate_limit_remaining"],
                    rate_limit_reset_at=row["rate_limit_reset_at"],
                )
                for row in rows
            ]
            self._index = 0
            self._rotation_attempts = 0
            self._last_refresh = time.monotonic()
            logger.info(
                "github token pool refreshed: %d active tokens loaded",
                len(self._available),
            )

    async def mark_current_rate_limited(
        self,
        reset_at: Optional[datetime] = None,
    ) -> None:
        """Mark the current token as rate-limited and remove it from the cache.

        Persists `rate_limit_remaining = 0` plus the reset timestamp and
        increments `failed_requests` in Supabase, then splices the token
        out of the local list. Defaults `reset_at` to now + 1 hour when
        the caller did not extract a reset header.
        """
        if reset_at is None:
            reset_at = datetime.now(tz=timezone.utc) + _DEFAULT_RATE_LIMIT_BACKOFF
        async with self._refresh_lock:
            if not self._available:
                logger.warning(
                    "mark_current_rate_limited called with empty pool; ignoring"
                )
                return
            if self._index >= len(self._available):
                self._index = 0
            token = self._available[self._index]
            try:
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        _MARK_RATE_LIMITED_SQL,
                        reset_at,
                        token.id,
                    )
            except Exception as exc:  # noqa: BLE001 -- transient DB errors
                logger.error(
                    "failed to persist rate-limit mark for token id=%s name=%s: %s",
                    token.id,
                    token.token_name,
                    exc,
                )
            logger.info(
                "github token rate-limited: id=%s name=%s reset_at=%s",
                token.id,
                token.token_name,
                reset_at.isoformat(),
            )
            self._available.pop(self._index)
            if self._index >= len(self._available):
                self._index = 0

    async def mark_success(
        self,
        rate_limit_remaining: Optional[int],
        rate_limit_reset_at: Optional[datetime],
    ) -> None:
        """Persist a successful API call's rate-limit headers for the current token.

        Updates the Supabase row and the in-memory token so subsequent
        proactive low-remaining checks read the new value without a
        round-trip.
        """
        async with self._refresh_lock:
            if not self._available:
                logger.warning("mark_success called with empty pool; ignoring")
                return
            if self._index >= len(self._available):
                self._index = 0
            token = self._available[self._index]
            try:
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        _MARK_SUCCESS_SQL,
                        rate_limit_remaining,
                        rate_limit_reset_at,
                        token.id,
                    )
            except Exception as exc:  # noqa: BLE001 -- transient DB errors
                logger.error(
                    "failed to persist success stats for token id=%s name=%s: %s",
                    token.id,
                    token.token_name,
                    exc,
                )
                return
            token.rate_limit_remaining = rate_limit_remaining
            token.rate_limit_reset_at = rate_limit_reset_at

    async def rotate_to_next(self) -> None:
        """Advance the active pointer to the next token, refreshing if exhausted.

        With one or zero tokens, force a refresh -- there is nothing to
        rotate to. Otherwise increment the pointer modulo pool size; if
        we have already cycled through every entry without success, force
        a refresh to pick up newly-recovered tokens.
        """
        async with self._refresh_lock:
            pool_size = len(self._available)
            if pool_size <= 1:
                needs_refresh = True
            else:
                self._index = (self._index + 1) % pool_size
                self._rotation_attempts += 1
                needs_refresh = self._rotation_attempts >= pool_size
                logger.info(
                    "github token rotated: index=%d attempts=%d/%d",
                    self._index,
                    self._rotation_attempts,
                    pool_size,
                )
        if needs_refresh:
            await self.refresh_tokens()

    def token_count(self) -> int:
        """Return the number of active tokens currently cached in memory."""
        return len(self._available)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _needs_refresh(self) -> bool:
        """Return True when the in-memory pool is empty or older than the TTL."""
        if not self._available:
            return True
        return time.monotonic() - self._last_refresh > _REFRESH_INTERVAL_SECONDS
