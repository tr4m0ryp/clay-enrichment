"""GeminiClient -- thin wrapper that routes every call through the api_keys pool.

Per D10/D12, all Gemini traffic now goes through
``src.api_keys.retry_with_fallback.gemini_generate_content``. Key selection,
tier descent, per-key 429 rotation, and the pool-level circuit breaker are
owned by ``KeyPoolManager`` -- this client never touches an env-var
``GEMINI_API_KEY`` and never imports the legacy sliding-window rate
limiter.

Public surface preserved:
    - class ``GeminiClient`` with ``__init__(config, rate_limiter=None)``
    - ``GeminiClient.generate(prompt, user_message, model=None,
      json_mode=False, temperature=0.1, grounding=False) -> dict``
      returning ``{"text": str, "input_tokens": int, "output_tokens": int,
      "served_model": str}``
    - ``GeminiClient.generate_batch(prompt, items, model=None,
      json_mode=True) -> dict`` returning
      ``{"results": list, "input_tokens": int, "output_tokens": int}``

The ``model`` and ``rate_limiter`` arguments are accepted for backward
compatibility with existing call sites but are no longer authoritative:
the pool picks the tier-appropriate model and the chokepoint's circuit
breaker subsumes the legacy rate limiter.

When ``grounding=True``, the call attaches ``tools=[{"google_search": {}}]``
to the REST request, restoring Google Search grounding parity with the
legacy SDK-based client. The system prompt is forwarded as a top-level
``system_instruction`` rather than concatenated into the user text. On
Gemini 3 the combined call also accepts ``json_mode=True``; the wrapper
no longer strips one when the other is set (see F3/R7 in
``research/campaign_creation_redesign.md``).

The ``generate()`` result dict carries ``served_model``, the model the
pool actually used on the wire (e.g. ``"gemini-3-pro-preview"``,
``"gemini-2.5-pro"``, ``"gemini-2.5-flash"``). It is the empty string
``""`` when the pool did not expose this metadata. Workers that depend
on Gemini 3-only features (combined grounded search + structured output
in one call) branch on the module-level helper ``is_gemini_3()`` and
fall back to a two-step path on tier downshift.
"""

from __future__ import annotations

import json
from typing import Any

from src.api_keys.retry_with_fallback import (
    GeminiPoolExhausted,
    GeminiResponse,
    gemini_generate_content,
)
from src.utils.logger import get_logger


logger = get_logger(__name__)


def _extract_token_counts(raw: dict) -> tuple[int, int]:
    """Return ``(input_tokens, output_tokens)`` from a Gemini REST body."""
    usage = raw.get("usageMetadata") if isinstance(raw, dict) else None
    if not isinstance(usage, dict):
        return 0, 0
    prompt_count = usage.get("promptTokenCount") or 0
    cand_count = usage.get("candidatesTokenCount") or 0
    try:
        return int(prompt_count), int(cand_count)
    except (TypeError, ValueError):
        return 0, 0


def _extract_served_model(response: GeminiResponse) -> str:
    """Return the model the pool actually served, or the empty string.

    Prefers ``raw["modelVersion"]`` (the model Gemini reports having
    served, which reflects any silent server-side downshift) and falls
    back to ``response.model_name`` (the model the pool requested on the
    wire). Returns ``""`` when neither is available so callers can rely
    on a stable string type.
    """
    raw = getattr(response, "raw", None)
    if isinstance(raw, dict):
        version = raw.get("modelVersion")
        if isinstance(version, str) and version:
            return version
    name = getattr(response, "model_name", "")
    if isinstance(name, str):
        return name
    return ""


def is_gemini_3(served_model: str) -> bool:
    """Return ``True`` if ``served_model`` belongs to the Gemini 3 family.

    Gemini 3 supports combined grounded search + structured output in a
    single call (per F3/R7); Gemini 2.5 does not. Workers branch on this
    to pick the single-call path versus the two-step (grounded research
    -> non-grounded structuring) fallback when the pool downshifts the
    tier.
    """
    return bool(served_model) and served_model.lower().startswith("gemini-3")


def _build_generation_config(
    *, json_mode: bool, temperature: float, grounding: bool,
) -> dict:
    """Translate legacy kwargs into the REST ``generationConfig`` dict.

    On Gemini 3, ``google_search`` grounding is compatible with
    ``responseMimeType=application/json`` in a single call (per F3/R7).
    The wrapper therefore attaches the JSON mime type whenever
    ``json_mode`` is requested, regardless of ``grounding``. ``grounding``
    is consumed at the call site (it controls the ``tools`` payload) and
    is accepted here only so the keyword surface is stable.
    """
    del grounding  # accepted for API symmetry; no longer affects the config
    cfg: dict[str, Any] = {"temperature": temperature}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    return cfg


_GOOGLE_SEARCH_TOOL: list[dict] = [{"google_search": {}}]


def _split_prompt(prompt: str, user_message: str) -> tuple[str | None, str]:
    """Return ``(system_instruction, user_text)`` for the REST request.

    Mirrors the legacy SDK split: the developer ``prompt`` becomes the
    top-level ``system_instruction`` and ``user_message`` is the single
    ``contents.parts.text``. If the system prompt is empty, returns
    ``None`` so the chokepoint omits the field. If the user message is
    empty, falls back to the system text alone (parity with the previous
    concatenation behaviour for callers that pass only one string).
    """
    system_part = (prompt or "").strip()
    user_part = (user_message or "").strip()
    if system_part and user_part:
        return system_part, user_part
    if user_part:
        return None, user_part
    return None, system_part


class GeminiClient:
    """Pool-backed Gemini client.

    The constructor accepts ``config`` and an optional ``rate_limiter``
    for backward compatibility with existing call sites; both are stored
    but only ``config.model_*`` defaults are read for diagnostic logging.
    Key selection and quota management are owned by the ``api_keys``
    subsystem.
    """

    def __init__(self, config, rate_limiter=None) -> None:
        """Store config; ``rate_limiter`` is accepted but unused.

        The legacy single-key + sliding-window rate limiter is replaced
        by the pool's per-key rotation and circuit breaker (D10/D12).
        We keep the parameter so ``main.py`` does not have to be edited
        to drop the now-redundant ``RateLimiter`` instance immediately.
        """
        self._config = config
        # Intentionally retained for signature compatibility; not read.
        self._rate_limiter = rate_limiter

    def _resolve_model(self, model: str | None) -> str:
        """Diagnostic-only: report what model the caller asked for.

        The pool's tier ladder picks the actual model that runs on the
        wire. This helper just returns a label for logging.
        """
        if model is not None:
            return model
        return getattr(self._config, "model_enrichment", "(pool-default)")

    async def generate(
        self,
        prompt: str,
        user_message: str,
        model: str = None,
        json_mode: bool = False,
        temperature: float = 0.1,
        grounding: bool = False,
        max_retries: int | None = None,
    ) -> dict:
        """Run a single Gemini call through the pool.

        Returns:
            ``{"text": str, "input_tokens": int, "output_tokens": int,
            "served_model": str}``. ``served_model`` is the model the
            pool actually used on the wire (``""`` if metadata was not
            exposed). Workers can pass it through ``is_gemini_3()`` to
            decide whether to take the single-call combined-tools path
            or fall back to the two-step path on tier downshift.

        Raises:
            ``GeminiPoolExhausted`` when the pool circuit is open beyond
            the chokepoint's wait budget. Callers should log + skip +
            persist their work item; the supervisor will retry the
            cycle later.
        """
        requested_model = self._resolve_model(model)
        system_instruction, user_text = _split_prompt(prompt, user_message)
        gen_config = _build_generation_config(
            json_mode=json_mode,
            temperature=temperature,
            grounding=grounding,
        )
        tools = _GOOGLE_SEARCH_TOOL if grounding else None

        kwargs: dict = {
            "generation_config": gen_config,
            "tools": tools,
            "system_instruction": system_instruction,
        }
        if max_retries is not None:
            kwargs["max_retries"] = max_retries

        # F16: Gemini 2.5 returns 400 on grounding + structured JSON in
        # one call. When the caller requests both, restrict the pool to
        # Gemini 3 tiers; the manager falls through to the private
        # Tier-1 backup if every harvested 3.x key is exhausted, so we
        # never waste a call on an incompatible 2.5 tier.
        if grounding and json_mode:
            from src.api_keys.types import GROUNDED_JSON_COMPATIBLE_MODELS
            kwargs["restrict_to_models"] = list(GROUNDED_JSON_COMPATIBLE_MODELS)

        try:
            response: GeminiResponse = await gemini_generate_content(
                user_text, **kwargs,
            )
        except GeminiPoolExhausted:
            logger.warning(
                "Gemini pool exhausted; skipping call (requested_model=%s).",
                requested_model,
            )
            raise

        input_tokens, output_tokens = _extract_token_counts(response.raw)
        served_model = _extract_served_model(response)
        return {
            "text": response.text or "",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "served_model": served_model,
        }

    async def generate_batch(
        self,
        prompt: str,
        items: list[str],
        model: str = None,
        json_mode: bool = True,
    ) -> dict:
        """Combine items into a single Gemini call and parse the JSON array.

        Items are joined with a numbered separator so the model can
        distinguish them. The response must be a JSON array with one
        element per input item.

        Returns:
            ``{"results": list, "input_tokens": int, "output_tokens": int}``
        """
        if not items:
            return {"results": [], "input_tokens": 0, "output_tokens": 0}

        parts = []
        for idx, item in enumerate(items, start=1):
            parts.append(f"--- Item {idx} ---\n{item}")
        combined = "\n\n".join(parts)
        batch_instruction = (
            f"{prompt}\n\n"
            "Process each item listed below and return a JSON array where each "
            "element corresponds to one item in the same order."
        )

        result = await self.generate(
            prompt=batch_instruction,
            user_message=combined,
            model=model,
            json_mode=json_mode,
        )

        text = result["text"].strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse batch JSON response: %s | raw=%r",
                exc, text[:500],
            )
            raise

        return {
            "results": parsed,
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
        }
