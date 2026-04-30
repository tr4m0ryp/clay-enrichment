"""Enrichment worker -- single ungrounded structured call per company.

Makes one Gemini call per ``Discovered`` company using the combined
research+structure prompt ``ENRICH_COMPANY_SINGLE_CALL`` with
``json_mode=True`` and ``grounding=False``. Grounding was dropped because
Gemini 2.5 returns HTTP 400 when grounding+json_mode are combined, and
the pool's free-tier keys regularly descend below Gemini 3 where the
combo would work. The prompt pins ``company_name`` + ``company_website``
so the model recalls the brand from training data; loses freshness on
recent news but gains reliability across the full tier ladder. Restore
once a stable F16 fallback (separate grounded research call followed
by non-grounded structuring) is wired in.

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
from src.enrichment.prompts.single_call import ENRICH_COMPANY_SINGLE_CALL
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)

_CONCURRENCY = 3
CYCLE_SLEEP_SECONDS = 240  # 4 min -- doubled to match the halved
# discovery cadence; keeps Gemini load steady and prevents over-
# enrichment of companies that are below the DPP-fit threshold.


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
    """Run a single ungrounded structured call to enrich the company.

    Grounding was dropped (alongside discovery / people / person_research)
    because Gemini 2.5 returns HTTP 400 when grounding=True and
    json_mode=True are combined, and the pool's free-tier keys frequently
    descend below Gemini 3 where the combo is supported. The prompt
    pins ``company_name`` + ``company_website`` so the model recalls
    the brand from training data; loses freshness on recent news but
    gains reliability across the full tier ladder. Restore once the
    F16 tier-aware fallback (separate grounded research call followed
    by non-grounded structuring) lands as a stable option.
    """
    rendered = (
        ENRICH_COMPANY_SINGLE_CALL
        .replace("{company_name}", name)
        .replace("{company_website}", website or "")
        .replace("{campaign_target}", campaign_target or "")
    )

    async def _call(user_message: str) -> dict:
        return await gemini_client.generate(
            prompt=rendered,
            user_message=user_message,
            grounding=False,
            json_mode=True,
            max_retries=30,
        )

    base_msg = f"Research and enrich the company: {name}"
    try:
        result = await retry_on_malformed_json(_call, base_msg)
    except Exception:
        logger.exception("Enrichment call raised for '%s'", name)
        return None

    if result is None:
        return None
    parsed, _raw = result
    if isinstance(parsed, list) and len(parsed) == 1:
        parsed = parsed[0]
    if isinstance(parsed, dict):
        return parsed
    return None



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
