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
      returning ``{"text": str, "input_tokens": int, "output_tokens": int}``
    - ``GeminiClient.generate_batch(prompt, items, model=None,
      json_mode=True) -> dict`` returning
      ``{"results": list, "input_tokens": int, "output_tokens": int}``

The ``model`` and ``rate_limiter`` arguments are accepted for backward
compatibility with existing call sites but are no longer authoritative:
the pool picks the tier-appropriate model and the chokepoint's circuit
breaker subsumes the legacy rate limiter.

Note: ``grounding=True`` (Google Search grounding) is not currently
plumbed through ``gemini_generate_content``. Calls made with
``grounding=True`` still execute, but without grounding tools attached;
the response text is the model's ungrounded answer.
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


def _build_generation_config(
    *, json_mode: bool, temperature: float, grounding: bool,
) -> dict:
    """Translate legacy kwargs into the REST ``generationConfig`` dict."""
    cfg: dict[str, Any] = {"temperature": temperature}
    if grounding and json_mode:
        # Mirror legacy behaviour: grounding takes precedence; json_mode
        # is incompatible with Google Search grounding in the REST API.
        logger.warning(
            "Grounding requested with json_mode=True; ignoring json_mode "
            "(incompatible with grounded responses)."
        )
    elif json_mode:
        cfg["responseMimeType"] = "application/json"
    return cfg


def _compose_prompt(prompt: str, user_message: str) -> str:
    """Concatenate system instruction and user message into a single text.

    The pool chokepoint exposes a single-text prompt parameter, not
    a system_instruction field. We preserve the legacy two-part call
    shape by stitching the system prompt above the user content.
    """
    system_part = (prompt or "").strip()
    user_part = (user_message or "").strip()
    if system_part and user_part:
        return f"{system_part}\n\n{user_part}"
    return system_part or user_part


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
    ) -> dict:
        """Run a single Gemini call through the pool.

        Returns:
            ``{"text": str, "input_tokens": int, "output_tokens": int}``

        Raises:
            ``GeminiPoolExhausted`` when the pool circuit is open beyond
            the chokepoint's wait budget. Callers should log + skip +
            persist their work item; the supervisor will retry the
            cycle later.
        """
        requested_model = self._resolve_model(model)
        full_prompt = _compose_prompt(prompt, user_message)
        gen_config = _build_generation_config(
            json_mode=json_mode,
            temperature=temperature,
            grounding=grounding,
        )

        try:
            response: GeminiResponse = await gemini_generate_content(
                full_prompt,
                generation_config=gen_config,
            )
        except GeminiPoolExhausted:
            logger.warning(
                "Gemini pool exhausted; skipping call (requested_model=%s).",
                requested_model,
            )
            raise

        input_tokens, output_tokens = _extract_token_counts(response.raw)
        return {
            "text": response.text or "",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
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
