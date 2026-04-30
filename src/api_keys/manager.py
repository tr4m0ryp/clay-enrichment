"""KeyPoolManager: tier ladder + circuit breaker over the validated key pool.

Sole writer of the gemini_tier_manager row's tier-state columns. Logs only
key UUIDs or 8-char prefixes -- never the full key_value.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
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

# Sentinel UUID + model name for the private last-resort key. The UUID
# never matches a real validated_keys row, so DB writes keyed on it
# (mark_quota_exceeded, mark_success, etc) are silent no-ops -- which
# is what we want, because the backup key isn't quota-tracked in DB,
# it's throttled per-process via _PRIVATE_KEY_MIN_INTERVAL.
_PRIVATE_KEY_SENTINEL_UUID = UUID("00000000-0000-0000-0000-000000000001")
# The private key serves Gemini 3 (Tier 1 paid plans have access).
# This matters for grounded+json_mode callers like the email_resolver's
# Gemini fallback finder: Gemini 2.5 rejects that combination in a
# single call (F16), Gemini 3 accepts it. Routing the private key to
# gemini-3-flash-preview lets those callers actually succeed when the
# harvested pool's Gemini-3 keys are 429-d.
_PRIVATE_KEY_DEFAULT_MODEL = "gemini-3-flash-preview"
# Cap private-key usage: max 1 call every 2 seconds per process.
# Rate-limit Gemini Tier 1 free is plenty for that. Keeps the pool
# returning to harvested keys whenever they recover.
_PRIVATE_KEY_MIN_INTERVAL = 2.0
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

    def __init__(
        self,
        pool: asyncpg.Pool,
        private_api_key: str = "",
    ) -> None:
        self._pool = pool
        # Tier 1 personal Gemini key, reserved for "harvested pool empty
        # at every tier" fallback. Empty string disables the fallback.
        self._private_api_key = (private_api_key or "").strip()
        self._private_last_used_monotonic: float = 0.0
        self._private_lock = asyncio.Lock()
        if self._private_api_key:
            logger.info(
                "KeyPoolManager: private backup key configured "
                "(%s)", _key_prefix(self._private_api_key),
            )

    async def _try_private_fallback(
        self, reason: str,
    ) -> Optional[tuple[UUID, str, str]]:
        """Hand out the private key when the harvested pool can't.

        Throttled to one call per ``_PRIVATE_KEY_MIN_INTERVAL`` seconds
        across the whole process so we don't burn the user's personal
        quota during a sustained harvested-pool outage. Returns None
        when no private key is configured.
        """
        if not self._private_api_key:
            return None
        async with self._private_lock:
            now = time.monotonic()
            wait = self._private_last_used_monotonic + _PRIVATE_KEY_MIN_INTERVAL - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._private_last_used_monotonic = time.monotonic()
        logger.warning(
            "private_key_fallback: reason=%s prefix=%s model=%s",
            reason, _key_prefix(self._private_api_key),
            _PRIVATE_KEY_DEFAULT_MODEL,
        )
        return (
            _PRIVATE_KEY_SENTINEL_UUID,
            self._private_api_key,
            _PRIVATE_KEY_DEFAULT_MODEL,
        )

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
                # Circuit is open -- but if we haven't probed for a while,
                # try once before giving up. This breaks the deadlock where
                # the pool descended to a permanently-broken bottom rung
                # and then opened the circuit, with no path back up.
                stale_probe = (
                    last_probe_at is None
                    or (now - last_probe_at) > timedelta(minutes=5)
                )
                if stale_probe:
                    logger.info(
                        "circuit open until %s -- attempting recovery probe "
                        "(last probe %s)",
                        circuit_open_until.isoformat(),
                        last_probe_at.isoformat() if last_probe_at else "never",
                    )
                    if await self.recovery_probe():
                        # Probe flipped active_tier up; re-read state next iter.
                        continue
                logger.info("circuit open until %s", circuit_open_until.isoformat())
                fallback = await self._try_private_fallback("circuit_open")
                return fallback
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

            # Don't slam the circuit open for hours when the only thing
            # blocking us is per-(key, model) cooldowns that expire in
            # seconds. If any valid key has a cooldown_until within the
            # next 10 minutes for any generative model, this is a
            # transient cooldown sweep -- return None and let the
            # caller's circuit_pause loop ride it out.
            if await self._has_imminent_cooldown_expiry(window_seconds=600):
                logger.info(
                    "no key available now, but cooldowns expire within "
                    "10min -- skipping circuit-open, letting caller wait",
                )
                fallback = await self._try_private_fallback("imminent_cooldown")
                return fallback

            await self._open_circuit()
            fallback = await self._try_private_fallback("all_tiers_exhausted")
            return fallback
        fallback = await self._try_private_fallback("descent_exhausted")
        return fallback

    async def _has_imminent_cooldown_expiry(self, window_seconds: int) -> bool:
        """Return True if any valid key has a cooldown ending within `window_seconds`.

        Used to decide whether to skip a long-duration circuit open: if
        cooldowns are about to expire, the pool will recover on its own
        within the caller's circuit_pause loop.
        """
        sql = """
            SELECT 1 FROM validated_keys vk,
                 jsonb_each(vk.capabilities) AS cap(model_name, props)
            WHERE vk.status = 'valid'
              AND vk.consecutive_failures < 3
              AND (cap.props ->> 'is_accessible')::bool = true
              AND (cap.props ->> 'cooldown_until') IS NOT NULL
              AND (cap.props ->> 'cooldown_until')::timestamptz
                  < (now() + ($1::int * interval '1 second'))
            LIMIT 1
        """
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(sql, int(window_seconds))
            return row is not None
        except Exception:
            logger.warning("cooldown-expiry probe failed", exc_info=True)
            return False

    async def mark_success(self, key_id: UUID, model_name: str, latency_ms: int) -> None:
        """Reset consecutive_failures on a successful Gemini call."""
        if key_id == _PRIVATE_KEY_SENTINEL_UUID:
            # Private key isn't quota-tracked in DB; success is fine.
            return
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
        if key_id == _PRIVATE_KEY_SENTINEL_UUID:
            # Private key throttle is per-process; if Tier 1 truly 429s,
            # the per-call interval already paces us. No DB cooldown.
            logger.warning(
                "private_key 429 -- next call gated by %.1fs interval",
                _PRIVATE_KEY_MIN_INTERVAL,
            )
            return
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
        if key_id == _PRIVATE_KEY_SENTINEL_UUID:
            logger.error("private_key reported INVALID: %s", reason)
            return
        await mark_validated_key_status(self._pool, key_id, "invalid")
        logger.warning("mark_invalid: key_id=%s reason=%s", key_id, reason)

    async def mark_model_denied(self, key_id: UUID, model_name: str) -> None:
        """Per-(key, model) PERMISSION_DENIED -- permanent capability off."""
        if key_id == _PRIVATE_KEY_SENTINEL_UUID:
            logger.warning(
                "private_key denied for model=%s -- not blocking pool",
                model_name,
            )
            return
        await update_validated_capability(
            self._pool, key_id, model_name, is_accessible=False
        )
        logger.warning("model_denied: key_id=%s model=%s", key_id, model_name)

    async def mark_model_unavailable(self, key_id: UUID, model_name: str) -> None:
        """Per-(key, model) MODEL_UNAVAILABLE -- treat as denied capability."""
        if key_id == _PRIVATE_KEY_SENTINEL_UUID:
            return
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
        """Walk the ladder picking the first key that exists, descending if not.

        Crucially: when ``pick_validated_key`` returns None at a tier, we
        check whether that tier has any key marked is_accessible=true
        (regardless of cooldown). If yes, the absence of pickable keys
        is a transient cooldown sweep -- we return None so the caller
        can wait, instead of descending past a healthy tier toward a
        broken one. Without this guard the active_tier got stuck at the
        bottom rung whenever upper-tier keys cooled down simultaneously.
        """
        cur: Optional[TierName] = active
        while cur is not None:
            picked = await pick_validated_key(self._pool, cur)
            if picked is not None:
                key_id, key_value = picked
                return key_id, key_value, cur
            if await self._has_accessible_keys(cur):
                logger.info(
                    "tier=%s has accessible keys but all are cooling down; "
                    "not descending", cur,
                )
                return None
            nxt = self._next_tier(cur)
            if nxt is None:
                return None
            await self._descend_to(cur, nxt)
            cur = nxt
        return None

    async def _has_accessible_keys(self, model: str) -> bool:
        """Return True if any valid key has is_accessible=true on `model`,
        regardless of cooldown_until. Used to distinguish "tier is healthy
        but cooling down" from "tier is permanently broken / no quota."
        """
        sql = """
            SELECT 1 FROM validated_keys
            WHERE status = 'valid'
              AND consecutive_failures < 3
              AND (capabilities -> $1 ->> 'is_accessible')::bool = true
            LIMIT 1
        """
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(sql, model)
            return row is not None
        except Exception:
            logger.warning("has_accessible_keys probe failed", exc_info=True)
            return False

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
        """Open the pool-level circuit (D10). Idempotent under concurrency.

        Default cap is now ~10 minutes (was 4h-or-midnight). The longer
        durations were appropriate when "circuit open" meant "every key
        permanently dead until daily quota reset" -- but with the
        cooldown-aware path (per F16/diagnostic), the circuit fires far
        more transiently (e.g. brief windows where every tier is
        cooling down or active_tier got stuck on a broken bottom rung).
        Reopening every 10 min lets the pool retry tier descent +
        recovery probes shortly after instead of getting stuck for
        hours.
        """
        now = _now_utc()
        # Default short circuit -- 10 min. Operators can override longer
        # via KEY_POOL_CIRCUIT_MAX_COOLDOWN_SEC.
        default_cap = timedelta(minutes=10)
        try:
            override = int(os.environ.get(
                "KEY_POOL_CIRCUIT_MAX_COOLDOWN_SEC", "0",
            ))
        except ValueError:
            override = 0
        cap = timedelta(seconds=override) if override > 0 else default_cap
        open_until = now + cap
        await update_system_status(
            self._pool, _SERVICE,
            state="circuit_open", circuit_open_until=open_until,
        )
        logger.error(
            "pool circuit OPEN until %s (cap=%ds)",
            open_until.isoformat(), int(cap.total_seconds()),
        )

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
