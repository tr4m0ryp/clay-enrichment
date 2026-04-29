"""Enrichment prompts package.

Re-exports the single-call combined research+structure prompt and the
legacy two-step prompts kept around for the Gemini 2.5 fallback path.
The single-call prompt is the default in the rewritten worker; the
two-step prompts run only when the api_keys pool downshifts the
served model below the Gemini 3 family (per F16).
"""

from __future__ import annotations

from src.enrichment.prompts.research import RESEARCH_COMPANY_GROUNDED
from src.enrichment.prompts.single_call import ENRICH_COMPANY_SINGLE_CALL
from src.enrichment.prompts.structure import STRUCTURE_COMPANY_ENRICHMENT

__all__ = (
    "ENRICH_COMPANY_SINGLE_CALL",
    "RESEARCH_COMPANY_GROUNDED",
    "STRUCTURE_COMPANY_ENRICHMENT",
)
