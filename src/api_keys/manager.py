"""KeyPoolManager: tier ladder + circuit breaker over the validated key pool.

Sole writer of the gemini_tier_manager row's tier-state columns. Logs only
key UUIDs or 8-char prefixes -- never the full key_value.
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from uuid import UUID

import asyncpg
import httpx

from src.api_keys.database import (
    get_system_status,
    increment_consecutive_failures,
    mark_validated_key_status,
    pick_validated_key,
    reset_consecutive_failures,
    set_capability_cooldown,
    update_system_status,
    update_validated_capability,
)
from src.api_keys.types import TIER_LADDER, TierName
from src.utils.logger import get_logger


logger = get_logger(__name__)

_SERVICE: str = "gemini_tier_manager"
_DEFAULT_MAX_COOLDOWN_SEC: int = 4 * 60 * 60
_OPPORTUNISTIC_PROBE_INTERVAL = timedelta(hours=1)
_PROBE_TIMEOUT_SECONDS: float = 30.0
_PROBE_BODY = {
    "contents": [{"parts": [{"text": "Hello"}]}],
    "generationConfig": {"maxOutputTokens": 10, "temperature": 0.1},
}

ActiveTier = Literal[
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "circuit_open",
]


def _key_prefix(key_value: str) -> str:
    """Short, log-safe prefix for a Gemini API key."""
    return f"{key_value[:8]}..." if key_value else "<empty>"


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


class KeyPoolManager:
    """Hands out validated Gemini keys for the currently active tier."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_key_for_active_tier(self) -> Optional[tuple[UUID, str, str]]:
        """Return (validated_key_id, key_value, model_name) or None on circuit open."""
        # At most one re-entry: opportunistic probe may move active_tier up.
        for _attempt in range(2):
            row = await get_system_status(self._pool, _SERVICE)
            now = _now_utc()
            active: TierName = (row["active_tier"] if row else None) or "gemini-2.5-pro"
            last_probe_at = row["last_recovery_probe_at"] if row else None
            circuit_open_until = row["circuit_open_until"] if row else None
            if circuit_open_until is not None and circuit_open_until > now:
                logger.info("circuit open until %s", circuit_open_until.isoformat())
                return None
            picked = await self._descend_until_key(active)
            if picked is not None:
                key_id, key_value, model_name = picked
                logger.info(
                    "tier handout: model=%s key_id=%s prefix=%s",
                    model_name, key_id, _key_prefix(key_value),
                )
                return key_id, key_value, model_name
            if self._should_opportunistic_probe(last_probe_at, now):
                logger.info(
                    "bottom rung empty -- opportunistic probe (last %s)",
                    last_probe_at.isoformat() if last_probe_at else "never",
                )
                if await self.recovery_probe():
                    continue  # active_tier may have moved up; retry descent.
            await self._open_circuit()
            return None
        return None

    async def mark_success(self, key_id: UUID, model_name: str, latency_ms: int) -> None:
        """Reset consecutive_failures on a successful Gemini call."""
        await reset_consecutive_failures(self._pool, key_id)
        # latency_ms accepted for API parity; rolling-stat tracking is deferred.
        _ = latency_ms
        _ = model_name

    async def mark_quota_exceeded(
        self,
        key_id: UUID,
        model_name: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        """A 429 on (key, model) -- transient, NOT a permanent capability denial.

        Per the per-minute-throttle diagnostic (every observed retry-after
        was 1.5-52s, never longer), Gemini 429s are recoverable rate-limit
        events, not quota exhaustion. We record a per-(key, model) cooldown
        so ``pick_validated_key`` skips this pair until the bucket refills,
        then the key returns to the rotation automatically. We do NOT flip
        ``is_accessible`` to false (would permanently block the key) and do
        NOT increment ``consecutive_failures`` (that circuit-breaker is
        reserved for genuine errors).
        """
        cooldown = retry_after_seconds if retry_after_seconds and retry_after_seconds > 0 else 65.0
        # Cap at 24h as a safety bound: even if Gemini reports a daily-window
        # retry, we keep the value bounded so a misparsed huge number can't
        # park a key forever.
        cooldown = min(cooldown, 86400.0)
        await set_capability_cooldown(self._pool, key_id, model_name, cooldown)
        logger.info(
            "quota_cooldown: key_id=%s model=%s cooldown=%.1fs",
            key_id, model_name, cooldown,
        )

    async def mark_invalid(self, key_id: UUID, reason: str) -> None:
        """Mark a key as globally invalid (Gemini reported API_KEY_INVALID)."""
        await mark_validated_key_status(self._pool, key_id, "invalid")
        logger.warning("mark_invalid: key_id=%s reason=%s", key_id, reason)

    async def mark_model_denied(self, key_id: UUID, model_name: str) -> None:
        """Per-(key, model) PERMISSION_DENIED -- permanent capability off."""
        await update_validated_capability(
            self._pool, key_id, model_name, is_accessible=False
        )
        logger.warning("model_denied: key_id=%s model=%s", key_id, model_name)

    async def mark_model_unavailable(self, key_id: UUID, model_name: str) -> None:
        """Per-(key, model) MODEL_UNAVAILABLE -- treat as denied capability."""
        await update_validated_capability(
            self._pool, key_id, model_name, is_accessible=False
        )
        logger.warning("model_unavailable: key_id=%s model=%s", key_id, model_name)

    async def active_tier(self) -> ActiveTier:
        """Return the active tier or 'circuit_open' if the breaker is engaged."""
        row = await get_system_status(self._pool, _SERVICE)
        if row is None:
            return "gemini-2.5-pro"
        circuit_open_until = row["circuit_open_until"]
        if circuit_open_until is not None and circuit_open_until > _now_utc():
            return "circuit_open"
        return (row["active_tier"] or "gemini-2.5-pro")  # type: ignore[return-value]

    async def recovery_probe(self) -> bool:
        """Probe upward from active_tier; flip up on each 200. Returns True if any flip."""
        row = await get_system_status(self._pool, _SERVICE)
        now = _now_utc()
        active: TierName = (row["active_tier"] if row else None) or "gemini-2.5-pro"
        was_circuit_open = bool(
            row
            and row["circuit_open_until"] is not None
            and row["circuit_open_until"] > now
        )
        targets = self._upward_targets(active)
        if not targets:
            await update_system_status(self._pool, _SERVICE, last_recovery_probe_at=now)
            return False
        candidate = await self._pick_random_valid_key()
        if candidate is None:
            logger.info("recovery_probe: no eligible key in pool")
            await update_system_status(self._pool, _SERVICE, last_recovery_probe_at=now)
            return False
        key_id, key_value = candidate
        flipped_any = False
        for target in targets:
            ok = await self._probe_model(key_value, target)
            if not ok:
                logger.info(
                    "recovery_probe: target=%s key_id=%s prefix=%s -> fail",
                    target, key_id, _key_prefix(key_value),
                )
                break
            await self._flip_tier_up(target)
            await update_validated_capability(
                self._pool, key_id, target, is_accessible=True
            )
            logger.info(
                "recovery_probe: target=%s key_id=%s prefix=%s -> flipped up",
                target, key_id, _key_prefix(key_value),
            )
            flipped_any = True
        fields: dict[str, object] = {"last_recovery_probe_at": _now_utc()}
        if flipped_any and was_circuit_open:
            fields["state"] = "active"
            fields["circuit_open_until"] = None
        await update_system_status(self._pool, _SERVICE, **fields)
        return flipped_any

    async def _descend_until_key(self, active: TierName) -> Optional[tuple[UUID, str, str]]:
        """Walk the ladder picking the first key that exists, descending if not."""
        cur: Optional[TierName] = active
        while cur is not None:
            picked = await pick_validated_key(self._pool, cur)
            if picked is not None:
                key_id, key_value = picked
                return key_id, key_value, cur
            nxt = self._next_tier(cur)
            if nxt is None:
                return None
            await self._descend_to(cur, nxt)
            cur = nxt
        return None

    @staticmethod
    def _next_tier(t: TierName) -> Optional[TierName]:
        try:
            i = TIER_LADDER.index(t)
        except ValueError:
            return None
        return TIER_LADDER[i + 1] if i + 1 < len(TIER_LADDER) else None

    @staticmethod
    def _upward_targets(active: TierName) -> list[TierName]:
        """Tiers strictly above ``active`` ordered nearest-first."""
        try:
            i = TIER_LADDER.index(active)
        except ValueError:
            return []
        # TIER_LADDER is top -> bottom; upward targets are indices < i, walked
        # nearest-first so the immediate-next rung is probed before the top.
        return list(reversed(TIER_LADDER[:i]))

    async def _descend_to(self, from_tier: TierName, to_tier: TierName) -> None:
        fields: dict[str, object] = {"active_tier": to_tier}
        now = _now_utc()
        if from_tier == "gemini-2.5-pro":
            fields["tier_pro_exhausted_at"] = now
        elif from_tier == "gemini-3-flash-preview":
            fields["tier_3_exhausted_at"] = now
        await update_system_status(self._pool, _SERVICE, **fields)
        logger.warning("tier descent: %s -> %s", from_tier, to_tier)

    async def _flip_tier_up(self, target: TierName) -> None:
        fields: dict[str, object] = {"active_tier": target}
        if target == "gemini-2.5-pro":
            fields["tier_pro_exhausted_at"] = None
        elif target == "gemini-3-flash-preview":
            fields["tier_3_exhausted_at"] = None
        await update_system_status(self._pool, _SERVICE, **fields)

    async def _open_circuit(self) -> None:
        """Open the pool-level circuit (D10). Idempotent under concurrency."""
        now = _now_utc()
        four_hours = now + timedelta(hours=4)
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        jitter = timedelta(seconds=random.randint(0, 300))
        midnight_with_jitter = next_midnight + timedelta(minutes=5) + jitter
        open_until = min(four_hours, midnight_with_jitter)
        try:
            max_cooldown = int(os.environ.get(
                "KEY_POOL_CIRCUIT_MAX_COOLDOWN_SEC",
                str(_DEFAULT_MAX_COOLDOWN_SEC),
            ))
        except ValueError:
            max_cooldown = _DEFAULT_MAX_COOLDOWN_SEC
        open_until = min(open_until, now + timedelta(seconds=max_cooldown))
        await update_system_status(
            self._pool, _SERVICE,
            state="circuit_open", circuit_open_until=open_until,
        )
        logger.error("pool circuit OPEN until %s", open_until.isoformat())

    @staticmethod
    def _should_opportunistic_probe(last_probe_at: Optional[datetime], now: datetime) -> bool:
        if last_probe_at is None:
            return True
        return (now - last_probe_at) > _OPPORTUNISTIC_PROBE_INTERVAL

    async def _pick_random_valid_key(self) -> Optional[tuple[UUID, str]]:
        """Random valid key for the recovery probe; ignores capabilities."""
        sql = (
            "select id, key_value from validated_keys "
            "where status = 'valid' and consecutive_failures < 3 "
            "order by random() limit 1"
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql)
        if row is None:
            return None
        return row["id"], row["key_value"]

    async def _probe_model(self, api_key: str, model_name: str) -> bool:
        """1-token Hello probe; returns True only on HTTP 200."""
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent"
        )
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, headers=headers, json=_PROBE_BODY)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
            return False
        return resp.status_code == 200
