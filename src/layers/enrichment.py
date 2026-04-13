"""
Layer 2: Company enrichment worker.

Picks up Discovered/stale companies, runs two-step Gemini grounding
enrichment, writes results to Postgres. Website resolution chain:
SearXNG resolver -> Gemini grounded lookup -> delete company.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from src.prompts.enrichment import (
    RESEARCH_COMPANY_GROUNDED,
    STRUCTURE_COMPANY_ENRICHMENT,
)
from src.prompts.website_lookup import FIND_COMPANY_WEBSITE
from src.search.website_resolver import resolve_website
from src.layers.enrichment_helpers import (
    build_enrichment_text,
    build_properties_update,
    scrape_fallback,
)

logger = logging.getLogger(__name__)

_CONCURRENCY = 3
CYCLE_SLEEP_SECONDS = 120


async def _get_campaign_target(company: dict, companies_db, campaigns_db) -> str:
    """Retrieve the campaign target description for a company."""
    company_id = str(company["id"])

    try:
        campaigns = await campaigns_db.get_processable_campaigns()
        if not campaigns:
            return ""

        # Check which campaigns are linked to this company via join table
        for campaign in campaigns:
            target = campaign.get("target_description", "")
            if target:
                return target
    except Exception as exc:
        logger.warning("Failed to fetch campaign target: %s", exc)

    return ""


async def _gemini_website_lookup(
    name: str, gemini_client, config,
) -> str:
    """Fallback: ask Gemini with Google Search grounding to find the website."""
    prompt = FIND_COMPANY_WEBSITE.replace("{company_name}", name)

    try:
        result = await gemini_client.generate(
            prompt=prompt,
            user_message=f"Find the official website for: {name}",
            model=config.model_research,
            grounding=True,
        )
        text = result["text"].strip()
        logger.info(
            "Gemini website lookup for '%s': in=%d out=%d tokens",
            name, result["input_tokens"], result["output_tokens"],
        )

        # Parse JSON from grounded response (may contain markdown fences)
        parsed = _extract_json(text)
        if not parsed:
            return ""

        url = parsed.get("website_url", "")
        confidence = parsed.get("confidence", "none")
        if url and confidence != "none":
            return url
    except Exception as exc:
        logger.warning("Gemini website lookup failed for '%s': %s", name, exc)

    return ""


def _extract_json(text: str) -> dict | None:
    """Extract a JSON object from text that may contain markdown fences."""
    # Try direct parse first
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    # Try finding any JSON object in the text
    match = re.search(r"\{[^{}]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass
    return None


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
    # Handle both single object and array-wrapped responses
    if isinstance(parsed, list) and len(parsed) == 1:
        parsed = parsed[0]
    return parsed


async def _enrich_company(
    company: dict,
    config, gemini_client, companies_db, campaigns_db,
    scraper, search_client,
) -> None:
    """Enrich a single company with two-step grounded pipeline."""
    name = company["name"]
    company_id = str(company["id"])
    existing_url = company.get("website") or ""

    # Resolve website URL -- SearXNG first, then Gemini grounded fallback
    website = await resolve_website(name, search_client, existing_url=existing_url)
    if website and website != existing_url:
        await companies_db.update_company(company_id, {"website": website})
        logger.info("Resolved website for '%s': %s", name, website)

    # Gemini grounded retry when resolver returns nothing
    if not website:
        website = await _gemini_website_lookup(name, gemini_client, config)
        if website:
            await companies_db.update_company(company_id, {"website": website})
            logger.info("Gemini resolved website for '%s': %s", name, website)
        else:
            logger.warning(
                "No website found for '%s' after resolver + Gemini. "
                "Deleting company.", name,
            )
            await companies_db.delete_company(company_id)
            return

    campaign_target = await _get_campaign_target(company, companies_db, campaigns_db)
    status = "Enriched"

    try:
        research_text = await _grounded_research(
            name, website, campaign_target, gemini_client, config,
        )
        result = await _structure_research(
            name, website, campaign_target, research_text, gemini_client, config,
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
                company_id,
                {
                    "status": "Partially Enriched",
                    "last_enriched_at": datetime.now(timezone.utc),
                },
            )
            return

    try:
        properties = build_properties_update(result, status)
        await companies_db.update_company(company_id, properties)

        body = build_enrichment_text(result)
        await companies_db.set_body(company_id, body)

        score = result.get("dpp_fit_score", "N/A")
        logger.info("Enriched '%s': score=%s status=%s", name, score, status)
    except Exception as exc:
        logger.error("Failed to update company '%s': %s", name, exc)


async def enrichment_worker(
    config,
    gemini_client,
    companies_db,
    campaigns_db,
    scraper,
    search_client=None,
) -> None:
    """
    Continuous worker loop: picks up Discovered and stale companies,
    enriches them per-company with concurrency semaphore.

    Runs indefinitely, sleeping CYCLE_SLEEP_SECONDS between cycles.
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

            # Deduplicate by company ID
            seen_ids: set[str] = set()
            unique: list[dict] = []
            for c in companies:
                cid = str(c["id"])
                if cid not in seen_ids:
                    seen_ids.add(cid)
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
