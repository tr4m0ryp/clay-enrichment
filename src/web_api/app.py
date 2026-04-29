"""FastAPI service exposing campaign-brief endpoints to the Next.js web layer.

Routes Gemini calls through src.campaign_brief.service which uses the
api_keys pool (key rotation, tier descent, circuit breaker) -- the same
chokepoint as every other Gemini call in the pipeline.

Bind localhost only; the Next.js routes proxy to it.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.campaign_brief import generate_campaign_brief, regenerate_sample_email
from src.config import get_config
from src.gemini.client import GeminiClient
from src.utils.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Clay Brief Service", version="1.0.0")

_gemini_client: Optional[GeminiClient] = None


def _get_client() -> GeminiClient:
    """Lazily build a process-scoped GeminiClient.

    The client is a thin shim over src.api_keys.retry_with_fallback.
    gemini_generate_content; key rotation + tier descent + circuit breaker
    are owned by the api_keys pool. The rate_limiter argument is accepted
    for backward compatibility but unused.
    """
    global _gemini_client
    if _gemini_client is None:
        config = get_config()
        _gemini_client = GeminiClient(config, rate_limiter=None)
    return _gemini_client


class GenerateRequest(BaseModel):
    name: str = Field(..., max_length=100)
    target_description: str = Field(..., max_length=5000)
    sample_emails: Optional[list[str]] = Field(default=None)


class RegenerateRequest(BaseModel):
    name: str = Field(..., max_length=100)
    target_description: str = Field(default="", max_length=5000)
    prior_brief: dict
    user_feedback: str = Field(..., max_length=5000)


class BriefResponse(BaseModel):
    icp_brief: str
    voice_profile: str
    banned_phrases: list[str]
    sample_email_subject: str
    sample_email_body: str


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "service": "clay-brief"}


@app.post("/campaign-brief/generate", response_model=BriefResponse)
async def generate(req: GenerateRequest) -> BriefResponse:
    if not req.target_description.strip():
        raise HTTPException(
            status_code=400,
            detail="target_description must not be empty",
        )
    samples = [s for s in (req.sample_emails or []) if isinstance(s, str) and s.strip()]
    samples = samples[:3]

    logger.info(
        "generate: name=%r target_chars=%d samples=%d",
        req.name, len(req.target_description), len(samples),
    )
    try:
        result = await generate_campaign_brief(
            _get_client(),
            name=req.name,
            target_description=req.target_description,
            sample_emails=samples,
        )
    except Exception as exc:
        logger.exception("generate: upstream error")
        raise HTTPException(status_code=502, detail=f"Brief generation failed: {exc}")
    if result is None:
        raise HTTPException(
            status_code=502,
            detail="Gemini did not return a valid brief",
        )
    return _coerce(result)


@app.post("/campaign-brief/regenerate", response_model=BriefResponse)
async def regenerate(req: RegenerateRequest) -> BriefResponse:
    if not req.user_feedback.strip():
        raise HTTPException(
            status_code=400,
            detail="user_feedback must not be empty",
        )
    if not isinstance(req.prior_brief, dict):
        raise HTTPException(
            status_code=400,
            detail="prior_brief must be a JSON object",
        )

    logger.info(
        "regenerate: name=%r feedback_chars=%d",
        req.name, len(req.user_feedback),
    )
    try:
        result = await regenerate_sample_email(
            _get_client(),
            name=req.name,
            target_description=req.target_description,
            prior_brief=req.prior_brief,
            user_feedback=req.user_feedback,
        )
    except Exception as exc:
        logger.exception("regenerate: upstream error")
        raise HTTPException(status_code=502, detail=f"Regenerate failed: {exc}")
    if result is None:
        raise HTTPException(
            status_code=502,
            detail="Gemini did not return a valid regenerated brief",
        )
    return _coerce(result)


def _coerce(result: dict) -> BriefResponse:
    """Coerce a service-returned dict into BriefResponse, hardening string types."""
    return BriefResponse(
        icp_brief=str(result.get("icp_brief") or ""),
        voice_profile=str(result.get("voice_profile") or ""),
        banned_phrases=[
            str(p) for p in (result.get("banned_phrases") or []) if isinstance(p, str)
        ],
        sample_email_subject=str(result.get("sample_email_subject") or ""),
        sample_email_body=str(result.get("sample_email_body") or ""),
    )
