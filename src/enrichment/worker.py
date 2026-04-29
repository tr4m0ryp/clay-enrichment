"""Enrichment worker -- single-call Gemini grounded structured + tier fallback.

The default path makes one Gemini grounded structured call per company
(``google_search`` + ``responseMimeType=application/json`` in the same
request, per F3 / R7) using the combined research+structure prompt
``ENRICH_COMPANY_SINGLE_CALL``. When the api_keys pool reports a Gemini
2.5 fallback served the call (per F16), the worker transparently splits
into the legacy two-step path (``RESEARCH_COMPANY_GROUNDED`` ->
``STRUCTURE_COMPANY_ENRICHMENT``) producing an identical output schema.

Drops the website-resolver waterfall, the scrape fallback, and the
stale-refresh loop (per F8 / D8 / D9). The worker only picks
``Discovered`` companies; once enriched, data is treated as stable.
``scraper`` and ``search_client`` are no longer worker arguments.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from src.enrichment.helpers import build_enrichment_text, build_properties_update
from src.enrichment.prompts.research import RESEARCH_COMPANY_GROUNDED
from src.enrichment.prompts.single_call import ENRICH_COMPANY_SINGLE_CALL
from src.enrichment.prompts.structure import STRUCTURE_COMPANY_ENRICHMENT
from src.gemini.client import is_gemini_3
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)

_CONCURRENCY = 3
CYCLE_SLEEP_SECONDS = 120


async def enrichment_worker(
    config: Any,
    gemini_client: Any,
    companies_db: Any,
    campaigns_db: Any,
) -> None:
    """Continuous loop: enrich ``Discovered`` companies one at a time.

    Each cycle picks every company in ``Discovered`` status and enriches
    them concurrently up to ``_CONCURRENCY``. The worker no longer
    refreshes stale ``Enriched`` rows -- enriched data is treated as
    stable per D8.
    """
    del config  # legacy parameter; the pool picks the model now
    logger.info("Enrichment worker started")
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _bounded(company: dict) -> None:
        async with sem:
            await _enrich_company(
                company, gemini_client, companies_db, campaigns_db,
            )

    while True:
        try:
            companies = await companies_db.get_companies_by_status("Discovered")
            if companies:
                logger.info(
                    "Enrichment cycle: %d companies to process",
                    len(companies),
                )
                await asyncio.gather(*[_bounded(c) for c in companies])
            else:
                logger.debug("Enrichment cycle: no companies to process")
        except Exception as exc:
            logger.error("Enrichment cycle error: %s", exc)

        await asyncio.sleep(CYCLE_SLEEP_SECONDS)


async def _enrich_company(
    company: dict,
    gemini_client: Any,
    companies_db: Any,
    campaigns_db: Any,
) -> None:
    """Enrich one company. Persist the result or mark Partially Enriched."""
    company_id = str(company["id"])
    name = company["name"]
    existing_website = company.get("website") or ""
    campaign_target = await _get_campaign_target(company, campaigns_db)

    profile = await _grounded_enrichment(
        gemini_client, name, existing_website, campaign_target,
    )

    if not isinstance(profile, dict) or not profile:
        logger.warning(
            "Enrichment: no profile produced for '%s'; "
            "marking Partially Enriched", name,
        )
        await companies_db.update_company(
            company_id,
            {
                "status": "Partially Enriched",
                "last_enriched_at": datetime.now(timezone.utc),
            },
        )
        return

    # If the model surfaced a canonical website and we don't already have
    # one, persist it so downstream layers can use it.
    discovered_website = (profile.get("website") or "").strip()
    if discovered_website and not existing_website:
        await companies_db.update_company(
            company_id, {"website": discovered_website},
        )
        logger.info(
            "Enrichment resolved website for '%s': %s",
            name, discovered_website,
        )

    try:
        properties = build_properties_update(profile, "Enriched")
        await companies_db.update_company(company_id, properties)

        body = build_enrichment_text(profile)
        await companies_db.set_body(company_id, body)

        score = profile.get("dpp_fit_score", "?")
        logger.info(
            "Enriched '%s': score=%s status=Enriched", name, score,
        )
    except Exception as exc:
        logger.error("Failed to update company '%s': %s", name, exc)


async def _grounded_enrichment(
    gemini_client: Any,
    name: str,
    website: str,
    campaign_target: str,
) -> dict | None:
    """Run the single combined call; transparently fall back on Gemini 2.5.

    Path 1 (Gemini 3): one grounded structured call. The wrapper trusts
    the parsed dict when ``served_model`` reports the Gemini 3 family
    OR is empty (pool did not expose the metadata). The single-call
    prompt is tier-defended, so a strong-output dict from any tier is
    acceptable.
    Path 2 (legacy fallback): the parsed value was not a dict, the
    ``served_model`` reports a non-Gemini-3 family with a non-dict
    structure, or the call raised. Run the legacy two-step path
    (grounded research -> non-grounded structuring) so the output
    schema stays invariant.
    """
    rendered = (
        ENRICH_COMPANY_SINGLE_CALL
        .replace("{company_name}", name)
        .replace("{company_website}", website or "")
        .replace("{campaign_target}", campaign_target or "")
    )

    async def _single_call(user_message: str) -> dict:
        return await gemini_client.generate(
            prompt=rendered,
            user_message=user_message,
            grounding=True,
            json_mode=True,
        )

    base_msg = f"Research and enrich the company: {name}"
    try:
        result = await retry_on_malformed_json(_single_call, base_msg)
    except Exception:
        logger.exception(
            "Single-call enrichment raised for '%s'; "
            "trying legacy two-step", name,
        )
        result = None

    if result is not None:
        parsed, raw = result
        served_model = (
            raw.get("served_model", "") if isinstance(raw, dict) else ""
        )
        if isinstance(parsed, list) and len(parsed) == 1:
            parsed = parsed[0]
        if isinstance(parsed, dict) and (
            is_gemini_3(served_model) or not served_model
        ):
            return parsed
        logger.info(
            "Single-call enrichment for '%s' returned non-dict or "
            "non-Gemini-3 served_model=%r; falling back to two-step",
            name, served_model,
        )

    return await _legacy_two_step(
        gemini_client, name, website, campaign_target,
    )


async def _legacy_two_step(
    gemini_client: Any,
    name: str,
    website: str,
    campaign_target: str,
) -> dict | None:
    """Legacy fallback: grounded research -> non-grounded structuring."""
    research_prompt = (
        RESEARCH_COMPANY_GROUNDED
        .replace("{company_name}", name)
        .replace("{company_website}", website or "(none)")
        .replace(
            "{campaign_target}",
            campaign_target or "(no campaign target provided)",
        )
    )

    try:
        research_result = await gemini_client.generate(
            prompt=research_prompt,
            user_message=f"Research the company: {name}",
            grounding=True,
        )
    except Exception:
        logger.exception("Legacy research call failed for '%s'", name)
        return None

    research_text = (research_result.get("text") or "").strip()
    if not research_text:
        logger.warning(
            "Legacy research returned empty text for '%s'", name,
        )
        return None

    structure_prompt = (
        STRUCTURE_COMPANY_ENRICHMENT
        .replace("{company_name}", name)
        .replace("{company_website}", website or "(none)")
        .replace(
            "{campaign_target}",
            campaign_target or "(no campaign target provided)",
        )
        .replace("{research_text}", research_text)
    )

    async def _structure_call(user_message: str) -> dict:
        return await gemini_client.generate(
            prompt=structure_prompt,
            user_message=user_message,
            json_mode=True,
        )

    try:
        result = await retry_on_malformed_json(
            _structure_call, f"Structure the research for: {name}",
        )
    except Exception:
        logger.exception("Legacy structure call failed for '%s'", name)
        return None
    if result is None:
        return None

    parsed, _raw = result
    if isinstance(parsed, list) and len(parsed) == 1:
        parsed = parsed[0]
    return parsed if isinstance(parsed, dict) else None


async def _get_campaign_target(company: dict, campaigns_db: Any) -> str:
    """Return the first non-empty processable-campaign target, or ''."""
    del company  # current schema has no per-company campaign filter here
    try:
        campaigns = await campaigns_db.get_processable_campaigns()
        for camp in campaigns:
            target = camp.get("target_description", "")
            if target:
                return target
    except Exception as exc:
        logger.warning("Failed to fetch campaign target: %s", exc)
    return ""
