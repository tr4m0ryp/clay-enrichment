"""
Layer 2: Company enrichment worker.

Continuous async loop that picks up Discovered and stale companies,
runs two-step Gemini grounding enrichment per company, then writes
structured results back to Postgres (column updates + body text).

Step 1: Grounded web research via Google Search (free text).
Step 2: JSON structuring of research results.
Fallback: website scrape with legacy prompt on grounding failure.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from src.db.campaigns import CampaignsDB
from src.db.companies import CompaniesDB
from src.prompts.enrichment import (
    RESEARCH_COMPANY_GROUNDED,
    STRUCTURE_COMPANY_ENRICHMENT,
)
from src.search.website_resolver import resolve_website
from src.layers.enrichment_helpers import (
    build_enrichment_text,
    build_properties_update_pg,
    scrape_fallback,
)

logger = logging.getLogger(__name__)

_CONCURRENCY = 3
CYCLE_SLEEP_SECONDS = 120


async def _get_campaign_target(
    company: dict, campaigns_db: CampaignsDB, companies_db: CompaniesDB,
) -> str:
    """Retrieve the campaign target description for a company."""
    # Look up campaigns linked to this company via company_campaigns join table
    company_id = company["id"]
    rows = await companies_db._pool.fetch(
        "SELECT c.target_description FROM campaigns c "
        "JOIN company_campaigns cc ON c.id = cc.campaign_id "
        "WHERE cc.company_id = $1 LIMIT 1",
        company_id,
    )
    if rows:
        return rows[0]["target_description"] or ""
    return ""


async def _grounded_research(
    name: str, website: str, campaign_target: str, gemini_client, config,
) -> str:
    """Step 1: Run grounded web research via Google Search."""
    prompt = (
        RESEARCH_COMPANY_GROUNDED
        .replace("{company_name}", name)
        .replace("{company_website}", website or "(none)")
        .replace("{campaign_target}", campaign_target or "(no campaign target provided)")
    )

    result = await gemini_client.generate(
        prompt=prompt,
        user_message=f"Research the company: {name}",
        model=config.model_research,
        grounding=True,
    )

    text = result["text"].strip()
    logger.info(
        "Grounded research for '%s': in=%d out=%d tokens",
        name, result["input_tokens"], result["output_tokens"],
    )
    return text


async def _structure_research(
    name: str, website: str, campaign_target: str,
    research_text: str, gemini_client, config,
) -> dict:
    """Step 2: Structure research text into JSON profile."""
    prompt = (
        STRUCTURE_COMPANY_ENRICHMENT
        .replace("{company_name}", name)
        .replace("{company_website}", website or "(none)")
        .replace("{campaign_target}", campaign_target or "(no campaign target provided)")
        .replace("{research_text}", research_text)
    )

    result = await gemini_client.generate(
        prompt=prompt,
        user_message=f"Structure the research for: {name}",
        model=config.model_enrichment,
        json_mode=True,
    )

    text = result["text"].strip()
    logger.info(
        "Structuring for '%s': in=%d out=%d tokens",
        name, result["input_tokens"], result["output_tokens"],
    )

    parsed = json.loads(text)
    if isinstance(parsed, list) and len(parsed) == 1:
        parsed = parsed[0]
    return parsed


async def _enrich_company(
    company: dict,
    config, gemini_client, companies_db: CompaniesDB,
    campaigns_db: CampaignsDB, scraper, search_client,
) -> None:
    """Enrich a single company with two-step grounded pipeline."""
    name = company.get("name", "")
    page_id = str(company["id"])
    existing_url = company.get("website", "")

    # Resolve website URL
    website = await resolve_website(name, search_client, existing_url=existing_url)
    if website and website != existing_url:
        await companies_db.update_company(page_id, {"website": website})
        logger.info("Resolved website for '%s': %s", name, website)

    campaign_target = await _get_campaign_target(company, campaigns_db, companies_db)
    status = "Enriched"

    try:
        research_text = await _grounded_research(
            name, website or existing_url, campaign_target, gemini_client, config,
        )
        result = await _structure_research(
            name, website or existing_url, campaign_target,
            research_text, gemini_client, config,
        )
    except Exception as exc:
        logger.warning(
            "Grounded enrichment failed for '%s', falling back to scrape: %s",
            name, exc,
        )
        try:
            result = await scrape_fallback(
                name, website or existing_url, campaign_target,
                gemini_client, scraper,
            )
            status = "Partially Enriched"
        except Exception as fallback_exc:
            logger.error(
                "Scrape fallback also failed for '%s': %s", name, fallback_exc,
            )
            await companies_db.update_company(
                page_id,
                {"status": "Partially Enriched",
                 "last_enriched_at": datetime.now(timezone.utc)},
            )
            return

    try:
        properties = build_properties_update_pg(result, status)
        await companies_db.update_company(page_id, properties)

        body_text = build_enrichment_text(result)
        await companies_db.append_body(page_id, body_text)

        score = result.get("dpp_fit_score", "N/A")
        logger.info("Enriched '%s': score=%s status=%s", name, score, status)
    except Exception as exc:
        logger.error("Failed to update company '%s': %s", name, exc)


async def enrichment_worker(
    config,
    gemini_client,
    companies_db: CompaniesDB,
    campaigns_db: CampaignsDB,
    scraper,
    search_client=None,
) -> None:
    """
    Continuous worker loop: picks up Discovered and stale companies,
    enriches them per-company with concurrency semaphore.
    """
    logger.info("Enrichment worker started")
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _bounded(company: dict) -> None:
        async with sem:
            await _enrich_company(
                company, config, gemini_client,
                companies_db, campaigns_db, scraper, search_client,
            )

    while True:
        try:
            companies = await companies_db.get_companies_by_status("Discovered")
            stale = await companies_db.get_stale_companies(
                config.enrichment_stale_days,
            )
            companies.extend(stale)

            # Deduplicate by ID
            seen_ids: set[str] = set()
            unique: list[dict] = []
            for c in companies:
                pid = str(c["id"])
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    unique.append(c)

            if unique:
                logger.info(
                    "Enrichment cycle: %d companies to process", len(unique),
                )
                await asyncio.gather(*[_bounded(c) for c in unique])
            else:
                logger.debug("Enrichment cycle: no companies to process")

        except Exception as exc:
            logger.error("Enrichment cycle error: %s", exc)

        await asyncio.sleep(CYCLE_SLEEP_SECONDS)
