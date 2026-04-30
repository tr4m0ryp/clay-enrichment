"""Prospeo person enrichment with a multi-key pool.

Prospeo's free tier grants ~75-100 enrichments per account per month, so
we scale by configuring multiple API keys -- the pool rotates round-robin
across keys, parking any key hit by 429 / INSUFFICIENT_CREDITS errors for
an hour before retrying it (in case the limit was per-minute rather than
monthly), and permanently disabling keys that report INVALID_API_KEY.

Each enrichment returns ``email`` + ``linkedin_url`` + ``current_job_title``
for 1 credit. Setting ``enrich_mobile=True`` costs 10x credits but also
returns the verified mobile phone number -- gated behind the
``PROSPEO_ENRICH_MOBILE`` env flag so cheap email+LinkedIn lookups stay
the default at ~1000/month per 10-key pool while opt-in mobile pulls
drop the budget to ~100/month.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp
import asyncpg

logger = logging.getLogger(__name__)

PROSPEO_ENRICH_URL = "https://api.prospeo.io/enrich-person"
TIMEOUT_SECONDS = 30.0
EXHAUSTED_COOLDOWN = timedelta(hours=1)
# Per Prospeo docs: 1 credit/match, 10 credits/match when mobile
# revealed, 0 for "free_enrichment" (lifetime account dedup).
_CREDITS_EMAIL_ONLY = 1
_CREDITS_WITH_MOBILE = 10


@dataclass
class _KeyState:
    api_key: str
    exhausted_until: datetime | None = None
    permanently_dead: bool = False


@dataclass
class ProspeoResult:
    """Fields the caller persists from a successful enrichment.

    ``raw`` is the full response body so downstream code can mine
    additional fields (company data, job history, location) without
    re-running the call -- per Prospeo's docs, repeating the same
    enrichment is free for the lifetime of an account.
    """

    email: str = ""
    email_verified: bool = False
    linkedin_url: str = ""
    phone: str = ""
    job_title: str = ""
    raw: dict | None = None


class ProspeoFinder:
    """Async multi-key Prospeo client.

    Round-robins across keys to maximize free-tier coverage. Quota
    accounting is reactive -- we don't poll Prospeo's account-info
    endpoint, instead reacting to 429 / INSUFFICIENT_CREDITS error
    codes as the signal to rotate.
    """

    def __init__(
        self,
        api_keys: list[str],
        usage_pool: asyncpg.Pool | None = None,
    ):
        clean = [k.strip() for k in api_keys if k and k.strip()]
        self._keys = [_KeyState(api_key=k) for k in clean]
        self._cursor = 0
        self._lock = asyncio.Lock()
        # Optional asyncpg pool for usage logging. When set, every
        # credit-spending call is recorded to ``prospeo_usage`` so the
        # dashboard can render a "X / monthly_quota" progress bar.
        # Logging failures are swallowed -- never block a resolution
        # because we couldn't write a metrics row.
        self._usage_pool = usage_pool
        if not self._keys:
            logger.info("ProspeoFinder: no API keys configured -- disabled")
        else:
            logger.info(
                "ProspeoFinder: %d keys configured (usage_logging=%s)",
                len(self._keys),
                "on" if usage_pool is not None else "off",
            )

    @property
    def enabled(self) -> bool:
        return any(not s.permanently_dead for s in self._keys)

    async def _pick_key(self) -> _KeyState | None:
        """Return the next available key in round-robin order, or None
        when every key is either dead or in cooldown.
        """
        async with self._lock:
            now = datetime.utcnow()
            n = len(self._keys)
            if n == 0:
                return None
            for _ in range(n):
                state = self._keys[self._cursor]
                self._cursor = (self._cursor + 1) % n
                if state.permanently_dead:
                    continue
                if state.exhausted_until and state.exhausted_until > now:
                    continue
                state.exhausted_until = None
                return state
            return None

    async def _mark_exhausted(self, key: str) -> None:
        async with self._lock:
            for state in self._keys:
                if state.api_key == key:
                    state.exhausted_until = datetime.utcnow() + EXHAUSTED_COOLDOWN
                    break

    async def _mark_dead(self, key: str) -> None:
        async with self._lock:
            for state in self._keys:
                if state.api_key == key:
                    state.permanently_dead = True
                    logger.error(
                        "ProspeoFinder: key %s permanently disabled",
                        _redact(key),
                    )
                    break

    async def find(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        *,
        enrich_mobile: bool = False,
    ) -> ProspeoResult | None:
        """Enrich one (first, last, domain) triple.

        Returns ``None`` when:
          - first_name or domain is empty (no call made),
          - all keys are exhausted / dead,
          - Prospeo returns NO_MATCH or INVALID_DATAPOINTS for this
            specific contact (definitive miss, not a key issue),
          - a transport-level error occurs on every available key.

        On success returns a ``ProspeoResult`` whose fields are stripped
        and lower-cased where applicable. The caller decides how to
        persist them (email goes to contacts.email, linkedin_url to
        both contacts and contact_campaigns, phone to both, etc).
        """
        if not first_name or not domain:
            return None
        if not self.enabled:
            return None

        body = {
            "only_verified_email": False,
            "enrich_mobile": enrich_mobile,
            "only_verified_mobile": False,
            "data": {
                "first_name": first_name,
                "last_name": last_name or "",
                "company_website": domain,
            },
        }

        # Try keys until one resolves the contact, or we exhaust the
        # pool. Transport errors fall through to the next key; logical
        # errors (NO_MATCH) terminate immediately because they're not
        # retryable on a different key.
        for _ in range(len(self._keys)):
            state = await self._pick_key()
            if state is None:
                logger.warning(
                    "ProspeoFinder: all keys exhausted/dead for %s %s @ %s",
                    first_name, last_name, domain,
                )
                return None
            try:
                status, body_resp = await self._call_one(state.api_key, body)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "ProspeoFinder: HTTP error on key %s for %s %s @ %s: %s",
                    _redact(state.api_key), first_name, last_name, domain, exc,
                )
                continue

            error_code = (
                body_resp.get("error_code")
                if isinstance(body_resp, dict) else None
            )

            if (
                status == 200
                and isinstance(body_resp, dict)
                and not body_resp.get("error")
            ):
                result = self._extract(body_resp)
                if result.email or result.linkedin_url:
                    free_dedup = bool(body_resp.get("free_enrichment", False))
                    credits = (
                        0 if free_dedup
                        else (_CREDITS_WITH_MOBILE if enrich_mobile
                              else _CREDITS_EMAIL_ONLY)
                    )
                    logger.info(
                        "ProspeoFinder: hit on key %s for %s %s @ %s "
                        "(email=%s linkedin=%s phone=%s credits=%d "
                        "free_dedup=%s)",
                        _redact(state.api_key), first_name, last_name, domain,
                        bool(result.email), bool(result.linkedin_url),
                        bool(result.phone), credits, free_dedup,
                    )
                    await self._log_usage(
                        state.api_key, credits, domain, free_dedup,
                    )
                    return result
                # Empty result body -- treat as miss without rotating.
                return None

            if status == 401 or error_code == "INVALID_API_KEY":
                await self._mark_dead(state.api_key)
                continue

            if status == 429 or error_code in (
                "RATE_LIMITED", "INSUFFICIENT_CREDITS",
            ):
                logger.info(
                    "ProspeoFinder: key %s exhausted (status=%s code=%s); "
                    "rotating",
                    _redact(state.api_key), status, error_code,
                )
                await self._mark_exhausted(state.api_key)
                continue

            if error_code in ("NO_MATCH", "INVALID_DATAPOINTS"):
                logger.info(
                    "ProspeoFinder: %s for %s %s @ %s (definitive miss)",
                    error_code, first_name, last_name, domain,
                )
                return None

            logger.warning(
                "ProspeoFinder: unexpected error %s/%s for %s %s @ %s; "
                "body=%.200s",
                status, error_code, first_name, last_name, domain,
                str(body_resp),
            )
            return None

        return None

    async def _call_one(
        self, api_key: str, body: dict,
    ) -> tuple[int, dict | None]:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        headers = {"X-KEY": api_key, "Content-Type": "application/json"}
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(
                PROSPEO_ENRICH_URL, headers=headers, json=body,
            ) as r:
                try:
                    parsed = await r.json()
                except Exception:
                    parsed = None
                return r.status, parsed

    async def _log_usage(
        self,
        api_key: str,
        credits: int,
        domain: str,
        free_dedup: bool,
    ) -> None:
        """Record one credit-spending Prospeo call.

        Failures are swallowed -- never block a resolution because we
        couldn't write a metrics row. The dashboard re-derives the
        monthly counter from this table at read time.
        """
        if self._usage_pool is None:
            return
        try:
            async with self._usage_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO prospeo_usage
                        (key_prefix, credits, domain, free_dedup)
                    VALUES ($1, $2, $3, $4)
                    """,
                    _redact(api_key), int(credits), domain, bool(free_dedup),
                )
        except Exception:
            logger.exception(
                "ProspeoFinder: failed to log usage row "
                "(non-fatal -- continuing)",
            )

    @staticmethod
    def _extract(body: dict) -> ProspeoResult:
        person = body.get("person") or {}
        email_obj = person.get("email") or {}
        mobile_obj = person.get("mobile") or {}
        email = (email_obj.get("email") or "").strip().lower()
        email_verified = (
            (email_obj.get("status") or "").upper() == "VERIFIED"
        )
        linkedin_url = (person.get("linkedin_url") or "").strip()
        # Prefer the international form so the dashboard renders a
        # clickable tel: link without country-code ambiguity.
        phone = (
            mobile_obj.get("mobile_international")
            or mobile_obj.get("mobile")
            or ""
        ).strip()
        job_title = (person.get("current_job_title") or "").strip()
        return ProspeoResult(
            email=email,
            email_verified=email_verified,
            linkedin_url=linkedin_url,
            phone=phone,
            job_title=job_title,
            raw=body,
        )


def _redact(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return key[:4] + "..." + key[-2:]
