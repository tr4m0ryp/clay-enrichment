"""Gemini API key validator.

Probes a candidate key against gemini-2.5-pro, gemini-3-flash-preview, and
gemini-2.5-flash (D11) in parallel, records per-(key, model) accessibility,
and derives an overall key status. Pure: builds a KeyValidationResult and
returns it; persistence is the caller's job (database.upsert_validated_key).

Ports FrogBytes_V3/lib/api-keys/validator.ts with the spec adjustments in
notes/gemini-scraper-supabase-db-refactor.md (Validator section, lines 347-446).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import httpx

from src.api_keys.types import (
    CapabilitySummary, KeyValidationResult, ModelCapability,
    RateLimitInfo, ScrapedKey, ValidationStatus,
)
from src.utils.logger import get_logger


logger = get_logger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
PROBE_TIMEOUT_SECONDS = 30.0
KEY_LEVEL_CONCURRENCY = 5
INTER_KEY_DELAY_SECONDS = 1.0

_MAX_TOKENS = 1_048_576
_MEDIA = ["text", "images", "video", "audio"]
_BASE = ["code-execution", "function-calling"]
GEMINI_VALIDATION_MODELS: list[dict[str, Any]] = [
    {"name": "gemini-2.5-pro", "endpoint": "generateContent", "max_tokens": _MAX_TOKENS,
     "features": _MEDIA + ["pdf"] + _BASE + ["search-grounding", "thinking"]},
    {"name": "gemini-3-flash-preview", "endpoint": "generateContent", "max_tokens": _MAX_TOKENS,
     "features": _MEDIA + ["pdf"] + _BASE + ["thinking"]},
    {"name": "gemini-2.5-flash", "endpoint": "generateContent", "max_tokens": _MAX_TOKENS,
     "features": _MEDIA + _BASE},
]

_INVALID_MARKERS = ("API_KEY_INVALID", "API key not valid")
_PROBE_BODY = {
    "contents": [{"parts": [{"text": "Hello"}]}],
    "generationConfig": {"maxOutputTokens": 10, "temperature": 0.1},
}


def _redact(api_key: str) -> str:
    """Return a non-sensitive prefix of the key for logs."""
    return f"{api_key[:8]}..." if len(api_key) >= 8 else "..."


def _error_envelope(payload: Any) -> tuple[str, Optional[str]]:
    """Return (scannable_text, error_message) extracted from a Gemini error.

    scannable_text joins error.message, error.status, and every
    error.details[*].reason for substring marker checks; error_message is
    the raw error.message (or None).
    """
    if not isinstance(payload, dict):
        return "", None
    err = payload.get("error")
    if not isinstance(err, dict):
        return "", None
    parts: list[str] = []
    msg = err.get("message")
    if isinstance(msg, str):
        parts.append(msg)
    status = err.get("status")
    if isinstance(status, str):
        parts.append(status)
    details = err.get("details")
    if isinstance(details, list):
        for entry in details:
            if isinstance(entry, dict):
                reason = entry.get("reason")
                if isinstance(reason, str):
                    parts.append(reason)
    return " ".join(parts), msg if isinstance(msg, str) else None


def _cap(model: dict[str, Any], **fields: Any) -> ModelCapability:
    """Construct a ModelCapability with the model's name/max_tokens/features."""
    return ModelCapability(
        model_name=model["name"], max_tokens=model["max_tokens"],
        features=list(model["features"]), **fields,
    )


async def _probe_model(
    client: httpx.AsyncClient, api_key: str, model: dict[str, Any]
) -> ModelCapability:
    """Issue a generateContent probe; map per notes lines 391-397.

    200 -> accessible; 400/401/403 with API_KEY_INVALID -> terminal global
    invalid; 403 PERMISSION_DENIED -> per-model only; 429/404/5xx/network
    -> per-model inaccessible (key not globally invalidated).
    """
    url = f"{GEMINI_API_BASE}/models/{model['name']}:{model['endpoint']}"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    try:
        response = await client.post(
            url, headers=headers, json=_PROBE_BODY, timeout=PROBE_TIMEOUT_SECONDS
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        return _cap(
            model, is_accessible=False,
            response_time_ms=int((loop.time() - t0) * 1000),
            error_code="NETWORK_ERROR", error_message=str(exc),
        )

    elapsed_ms = int((loop.time() - t0) * 1000)
    status = response.status_code
    try:
        payload: Any = response.json()
    except ValueError:
        payload = None

    if status == 200:
        return _cap(model, is_accessible=True, response_time_ms=elapsed_ms)

    text, message = _error_envelope(payload)
    if status in (400, 401, 403) and any(m in text for m in _INVALID_MARKERS):
        code = "API_KEY_INVALID"
    elif status == 403 and "PERMISSION_DENIED" in text:
        code = "PERMISSION_DENIED"
    else:
        code = str(status)
    return _cap(
        model, is_accessible=False, response_time_ms=elapsed_ms,
        error_code=code, error_message=message or f"HTTP {status}",
    )


async def _fetch_quota_info(
    client: httpx.AsyncClient, api_key: str
) -> tuple[Optional[int], Optional[RateLimitInfo]]:
    """Best-effort quota probe via GET /models; failures return (None, None).

    Uses the ?key= query param here (read-only metadata, low risk).
    """
    try:
        response = await client.get(
            f"{GEMINI_API_BASE}/models",
            params={"key": api_key},
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.debug("quota probe failed for %s: %s", _redact(api_key), exc)
        return None, None
    if response.status_code != 200:
        return None, None
    rpm = response.headers.get("x-ratelimit-requests-per-minute")
    rpd = response.headers.get("x-ratelimit-requests-per-day")
    qr = response.headers.get("x-quota-remaining")
    rate_limit: Optional[RateLimitInfo] = None
    if rpm or rpd:
        rate_limit = RateLimitInfo(
            requests_per_minute=int(rpm) if rpm and rpm.isdigit() else None,
            requests_per_day=int(rpd) if rpd and rpd.isdigit() else None,
        )
    quota_remaining = int(qr) if qr and qr.lstrip("-").isdigit() else None
    return quota_remaining, rate_limit


def _derive_status(
    capabilities: list[ModelCapability], quota_remaining: Optional[int]
) -> ValidationStatus:
    """Status precedence: invalid > quota_reached > quota_exceeded > valid."""
    if any(c.error_code == "API_KEY_INVALID" for c in capabilities):
        return "invalid"
    if quota_remaining == 0:
        return "quota_reached"
    if capabilities and all(c.error_code == "429" for c in capabilities):
        return "quota_exceeded"
    if any(c.is_accessible for c in capabilities):
        return "valid"
    return "invalid"


async def validate_gemini_key(
    api_key: str, *, full: bool = False, client: Optional[httpx.AsyncClient] = None,
) -> KeyValidationResult:
    """Validate one Gemini key against the three target models in parallel.

    full=True also probes /models for rate-limit/quota headers. Network
    errors leave those fields None -- they never flip the key to invalid.
    """
    logger.info("validating key %s", _redact(api_key))
    own = client is None
    active = client or httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS)
    try:
        coros: list[Awaitable[ModelCapability]] = [
            _probe_model(active, api_key, m) for m in GEMINI_VALIDATION_MODELS
        ]
        gathered = await asyncio.gather(*coros, return_exceptions=True)
        capabilities: list[ModelCapability] = []
        for outcome in gathered:
            if isinstance(outcome, BaseException):
                capabilities.append(ModelCapability(
                    model_name="unknown", is_accessible=False,
                    error_code="exception", error_message=str(outcome),
                ))
            else:
                capabilities.append(outcome)
        if any(c.error_code == "API_KEY_INVALID" for c in capabilities):
            for cap in capabilities:
                cap.is_accessible = False
                if cap.error_code is None:
                    cap.error_code = "API_KEY_INVALID"
        quota_remaining: Optional[int] = None
        rate_limit: Optional[RateLimitInfo] = None
        if full:
            quota_remaining, rate_limit = await _fetch_quota_info(active, api_key)
    finally:
        if own:
            await active.aclose()

    latencies = [c.response_time_ms for c in capabilities if c.response_time_ms is not None]
    avg_ms = sum(latencies) / len(latencies) if latencies else None
    total_tested = len(GEMINI_VALIDATION_MODELS)
    total_accessible = sum(1 for c in capabilities if c.is_accessible)
    status = _derive_status(capabilities, quota_remaining)
    is_valid = total_accessible > 0 and status != "invalid"
    logger.info(
        "key %s -> status=%s accessible=%d/%d",
        _redact(api_key), status, total_accessible, total_tested,
    )
    return KeyValidationResult(
        key=api_key, is_valid=is_valid,
        validated_at=datetime.now(tz=timezone.utc),
        capabilities=capabilities,
        total_models_accessible=total_accessible,
        total_models_tested=total_tested,
        average_response_time_ms=avg_ms,
        quota_remaining=quota_remaining,
        rate_limit_info=rate_limit, status=status,
    )


async def validate_keys(
    keys: list[ScrapedKey],
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> list[KeyValidationResult]:
    """Validate many keys at concurrency 5 with a 1.0s inter-key delay (notes 446)."""
    total = len(keys)
    if total == 0:
        return []
    sem = asyncio.Semaphore(KEY_LEVEL_CONCURRENCY)
    completed = 0
    progress_lock = asyncio.Lock()

    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        async def _run(index: int, scraped: ScrapedKey) -> KeyValidationResult:
            nonlocal completed
            async with sem:
                try:
                    result = await validate_gemini_key(
                        scraped.key, full=False, client=client
                    )
                finally:
                    if index < total - 1:
                        await asyncio.sleep(INTER_KEY_DELAY_SECONDS)
            async with progress_lock:
                completed += 1
                if on_progress is not None:
                    try:
                        on_progress(completed, total, _redact(scraped.key))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("on_progress callback raised: %s", exc)
            return result

        tasks = [asyncio.create_task(_run(i, k)) for i, k in enumerate(keys)]
        results = await asyncio.gather(*tasks)

    logger.info("validated %d/%d keys", sum(1 for r in results if r.is_valid), total)
    return results


def get_capability_summary(result: KeyValidationResult) -> CapabilitySummary:
    """Map a validation result into the dashboard's per-tier flag triplet."""
    accessible = [c.model_name for c in result.capabilities if c.is_accessible]
    return CapabilitySummary(
        has_pro="gemini-2.5-pro" in accessible,
        has_3_flash_preview="gemini-3-flash-preview" in accessible,
        has_25_flash="gemini-2.5-flash" in accessible,
        accessible_models=accessible,
    )
