"""Single chokepoint between clay-enrichment business logic and Gemini.

Wraps key rotation, per-model 403/404, per-key 429 and tier descent behind
``gemini_generate_content``. Surfaces only a successful ``GeminiResponse``
or ``GeminiPoolExhausted`` when the pool circuit stays open past
``max_circuit_waits`` cycles.

Per rules.md: never log ``key_value`` and never log full prompt text;
truncate prompts to 200 characters in any log line.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from time import monotonic
from typing import Optional
from uuid import UUID

import httpx

from src.api_keys.manager import KeyPoolManager
from src.api_keys.supabase_client import get_supabase_pool
from src.utils.logger import get_logger


logger = get_logger(__name__)

_GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
_DEFAULT_HTTP_TIMEOUT_SECONDS: float = 240.0  # 4 min -- grounded
# Gemini 3 calls can take 30-60s in normal conditions and occasionally
# 90-180s when the search portion expands. The previous 60s budget was
# too aggressive and turned slow-but-working calls into ReadTimeout
# errors, which then counted as a finder failure. Non-grounded calls
# finish in 1-3s anyway so the longer ceiling doesn't slow them down.
_PROMPT_LOG_TRUNCATE: int = 200


class GeminiPoolExhausted(Exception):
    """Raised when the pool circuit is open and max_circuit_waits exhausted."""


@dataclass(slots=True)
class GeminiResponse:
    """Successful Gemini response surfaced to callers."""

    text: str
    model_name: str
    raw: dict
    latency_ms: int


_default_manager: Optional[KeyPoolManager] = None
_default_client: Optional[httpx.AsyncClient] = None


async def _get_default_manager() -> KeyPoolManager:
    """Return a process-scoped ``KeyPoolManager`` over the Supabase pool.

    The optional ``PRIVATE_GEMINI_API_KEY`` env var (read once at first
    construction) is wired in as a last-resort backup -- the manager
    only surfaces it when every harvested key is exhausted across all
    tiers. Empty / unset means no fallback.
    """
    global _default_manager
    if _default_manager is None:
        pool = await get_supabase_pool()
        private_key = os.environ.get("PRIVATE_GEMINI_API_KEY", "").strip()
        _default_manager = KeyPoolManager(
            pool=pool,
            private_api_key=private_key,
        )
    return _default_manager


def _get_default_client() -> httpx.AsyncClient:
    """Return a process-scoped ``httpx.AsyncClient`` shared across calls."""
    global _default_client
    if _default_client is None:
        _default_client = httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_SECONDS)
    return _default_client


def _safe_json(resp: httpx.Response) -> dict:
    """Return parsed JSON or a fallback dict carrying the raw body text."""
    try:
        body = resp.json()
    except Exception:
        return {"_raw_body": resp.text}
    if isinstance(body, dict):
        return body
    return {"_raw_body": body}


def _extract_retry_after(body: dict, headers) -> Optional[float]:
    """Extract a per-minute cooldown duration in seconds from a 429 response.

    Gemini 429s include a "Please retry in Xs" string in the error message
    (per the per-minute-throttle diagnostic). Falls back to the Retry-After
    HTTP header (which is always integer seconds). Returns None when no
    parseable hint is present; the manager then uses a default cooldown.
    """
    import re

    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        msg = error.get("message")
        if isinstance(msg, str):
            m = re.search(r"retry in ([\d.]+)\s*s", msg)
            if m:
                try:
                    return float(m.group(1))
                except (TypeError, ValueError):
                    pass
    if headers is not None:
        ra = headers.get("Retry-After") or headers.get("retry-after")
        if ra:
            try:
                return float(ra)
            except (TypeError, ValueError):
                pass
    return None


def _is_invalid_key(body: dict) -> bool:
    """Detect ``API_KEY_INVALID`` / ``API key not valid`` in a Gemini error body."""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return False
    msg = error.get("message", "") or ""
    if not isinstance(msg, str):
        return False
    return "API_KEY_INVALID" in msg or "API key not valid" in msg


def _extract_text(body: dict) -> str:
    """Concatenate ``candidates[0].content.parts[].text`` from a Gemini body."""
    candidates = body.get("candidates") if isinstance(body, dict) else None
    if not candidates or not isinstance(candidates, list):
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    content = first.get("content") or {}
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts") or []
    if not isinstance(parts, list):
        return ""
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text", "")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks)


def _key_id_prefix(key_id: UUID) -> str:
    """Short, log-safe prefix for a validated_keys.id."""
    s = str(key_id)
    return s[:8] if s else "<empty>"


def _prompt_preview(prompt: str) -> str:
    """Truncate the prompt to a fixed length for safe logging."""
    if not isinstance(prompt, str):
        return ""
    if len(prompt) <= _PROMPT_LOG_TRUNCATE:
        return prompt
    return prompt[:_PROMPT_LOG_TRUNCATE] + "..."


async def _safe_mark(coro, label: str) -> None:
    """Run a manager.mark_* coroutine, logging any failure without raising."""
    try:
        await coro
    except Exception as exc:
        logger.warning("%s failed: %s", label, exc)


async def gemini_generate_content(
    prompt: str,
    *,
    generation_config: Optional[dict] = None,
    tools: Optional[list[dict]] = None,
    system_instruction: Optional[str] = None,
    max_retries: int = 5,
    circuit_pause_sec: int = 60,
    max_circuit_waits: int = 3,
    manager: Optional[KeyPoolManager] = None,
    client: Optional[httpx.AsyncClient] = None,
    restrict_to_models: Optional[list[str]] = None,
) -> GeminiResponse:
    """Run a Gemini generateContent call through the pool with full fallback.

    Absorbs per-key 429s, per-model 403/404, per-key invalidation,
    network errors, and tier descent. The only failure mode visible to
    callers is :class:`GeminiPoolExhausted`, raised when the pool circuit
    has been open for ``max_circuit_waits`` consecutive cycles or when
    ``max_retries`` have been spent without a 200.

    Optional ``tools`` (e.g. ``[{"google_search": {}}]`` for Google Search
    grounding) and ``system_instruction`` (top-level system prompt) are
    forwarded into the REST request body when provided.

    ``restrict_to_models``: when set, only keys serving one of the listed
    Gemini models are eligible. Used by callers that need a feature only
    some model tiers support (e.g. grounded structured output requires
    Gemini 3.x). The manager walks ``restrict_to_models`` in order and
    falls through to the private Tier-1 backup when all listed tiers
    are exhausted -- it never descends to incompatible 2.5 tiers.
    """
    mgr = manager if manager is not None else await _get_default_manager()
    http = client if client is not None else _get_default_client()

    payload: dict[str, object] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config or {},
    }
    if tools is not None:
        payload["tools"] = tools
    if system_instruction is not None:
        payload["system_instruction"] = {
            "parts": [{"text": system_instruction}],
        }

    attempt = 0
    circuit_waits = 0
    while attempt < max_retries:
        try:
            if restrict_to_models:
                key_info = await mgr.get_key_for_models(restrict_to_models)
            else:
                key_info = await mgr.get_key_for_active_tier()
        except Exception as exc:
            logger.warning(
                "manager.get_key_for_active_tier failed: %s; preview=%r",
                exc,
                _prompt_preview(prompt),
            )
            attempt += 1
            continue

        if key_info is None:
            if circuit_waits >= max_circuit_waits:
                logger.error(
                    "GeminiPoolExhausted: circuit open beyond max waits=%s",
                    max_circuit_waits,
                )
                raise GeminiPoolExhausted("circuit open, exceeded max waits")
            circuit_waits += 1
            logger.warning(
                "circuit open; waiting %ss (cycle %s/%s)",
                circuit_pause_sec,
                circuit_waits,
                max_circuit_waits,
            )
            await asyncio.sleep(circuit_pause_sec)
            continue

        key_id, key_value, model_name = key_info
        url = _GEMINI_ENDPOINT.format(model=model_name)
        headers = {
            "x-goog-api-key": key_value,
            "Content-Type": "application/json",
        }
        start = monotonic()
        try:
            resp = await http.post(
                url,
                headers=headers,
                json=payload,
                timeout=_DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            # Covers TimeoutException, NetworkError, RemoteProtocolError, etc.
            logger.warning(
                "gemini transport error: %s key_id=%s model=%s",
                exc.__class__.__name__,
                _key_id_prefix(key_id),
                model_name,
            )
            attempt += 1
            continue
        latency_ms = int((monotonic() - start) * 1000)
        body = _safe_json(resp)

        prefix = _key_id_prefix(key_id)
        if resp.status_code == 200:
            await _safe_mark(
                mgr.mark_success(key_id, model_name, latency_ms), "mark_success"
            )
            logger.info(
                "gemini ok: model=%s key_id=%s latency_ms=%s",
                model_name, prefix, latency_ms,
            )
            return GeminiResponse(
                text=_extract_text(body),
                model_name=model_name,
                raw=body,
                latency_ms=latency_ms,
            )

        if resp.status_code == 429:
            retry_after = _extract_retry_after(body, resp.headers)
            logger.warning(
                "gemini 429 quota: key_id=%s model=%s retry_after=%.1fs",
                prefix, model_name, retry_after if retry_after is not None else -1.0,
            )
            await _safe_mark(
                mgr.mark_quota_exceeded(key_id, model_name, retry_after),
                "mark_quota_exceeded",
            )
        elif resp.status_code in (400, 401, 403) and _is_invalid_key(body):
            logger.warning(
                "gemini invalid key: status=%s key_id=%s", resp.status_code, prefix
            )
            await _safe_mark(
                mgr.mark_invalid(key_id, "API_KEY_INVALID"), "mark_invalid"
            )
        elif resp.status_code == 403:
            logger.warning(
                "gemini 403 model_denied: key_id=%s model=%s", prefix, model_name
            )
            await _safe_mark(
                mgr.mark_model_denied(key_id, model_name), "mark_model_denied"
            )
        elif resp.status_code == 404:
            logger.warning(
                "gemini 404 model_unavailable: key_id=%s model=%s",
                prefix, model_name,
            )
            await _safe_mark(
                mgr.mark_model_unavailable(key_id, model_name),
                "mark_model_unavailable",
            )
        else:
            # 5xx or unexpected -- transient.
            logger.warning(
                "gemini transient: status=%s key_id=%s model=%s",
                resp.status_code, prefix, model_name,
            )
        attempt += 1
        continue

    logger.error(
        "GeminiPoolExhausted: max_retries=%s exhausted; preview=%r",
        max_retries,
        _prompt_preview(prompt),
    )
    raise GeminiPoolExhausted("max retries exceeded")
