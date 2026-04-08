import asyncio
import json
import logging
import time

from google import genai
from google.genai import types

from src.utils.logger import get_logger

logger = get_logger(__name__)


class GeminiClient:
    """Direct Gemini API client using the google-genai SDK."""

    def __init__(self, config, rate_limiter):
        """Initialize with config (for API key + model names) and rate limiter."""
        self._config = config
        self._rate_limiter = rate_limiter
        self._client = genai.Client(api_key=config.gemini_api_key)

    def _resolve_model(self, model: str | None) -> str:
        if model is not None:
            return model
        return self._config.model_enrichment

    async def generate(
        self,
        prompt: str,
        user_message: str,
        model: str = None,
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> dict:
        """
        Call the Gemini API and return text plus token counts.

        Returns:
            {"text": str, "input_tokens": int, "output_tokens": int}
        """
        resolved_model = self._resolve_model(model)
        await self._rate_limiter.acquire(resolved_model)

        config_kwargs: dict = {
            "temperature": temperature,
            "system_instruction": prompt,
        }
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

        gen_config = types.GenerateContentConfig(**config_kwargs)

        start = time.monotonic()
        try:
            response = await self._client.aio.models.generate_content(
                model=resolved_model,
                contents=user_message,
                config=gen_config,
            )
        except Exception as exc:
            logger.error("Gemini API error (model=%s): %s", resolved_model, exc)
            raise

        elapsed = time.monotonic() - start
        usage = response.usage_metadata
        input_tokens = (usage.prompt_token_count or 0) if usage else 0
        output_tokens = (usage.candidates_token_count or 0) if usage else 0
        text = response.text or ""

        logger.info(
            "Gemini call | model=%s | in=%d out=%d tokens | %.2fs",
            resolved_model,
            input_tokens,
            output_tokens,
            elapsed,
        )

        return {"text": text, "input_tokens": input_tokens, "output_tokens": output_tokens}

    async def generate_batch(
        self,
        prompt: str,
        items: list[str],
        model: str = None,
        json_mode: bool = True,
    ) -> dict:
        """
        Combine items into a single API call and return a parsed JSON array.

        Items are joined with a numbered separator so the model can distinguish
        them. The response must be a JSON array with one element per input item.

        Returns:
            {"results": list, "input_tokens": int, "output_tokens": int}
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
            logger.error("Failed to parse batch JSON response: %s | raw=%r", exc, text[:500])
            raise

        return {
            "results": parsed,
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
        }
