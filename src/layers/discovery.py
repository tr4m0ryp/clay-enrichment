"""
Layer 1: Company Discovery Worker.

Continuous async loop that polls active campaigns from Notion, generates
search queries via Gemini, runs searches via SearXNG (self-hosted meta-search),
extracts company names from results, and writes new companies to the Notion
Companies DB with dedup.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from src.models.gemini import GeminiClient
from src.notion.databases_campaigns import CampaignsDB
from src.notion.databases_companies import CompaniesDB
from src.notion.prop_helpers import extract_title, extract_rich_text
from src.prompts.discovery import GENERATE_SEARCH_QUERIES, PARSE_SEARCH_RESULTS
from src.utils.logger import get_logger

logger = get_logger(__name__)

_CYCLE_INTERVAL_SECONDS = 300  # 5 minutes between full cycles


@dataclass
class NotionClients:
    """Container for the Notion database helpers used by discovery."""

    campaigns: CampaignsDB
    companies: CompaniesDB


async def discovery_worker(
    config,
    gemini_client: GeminiClient,
    notion_clients: NotionClients,
    search_client: Any,
) -> None:
    """Continuous discovery loop. Runs forever, polling for active campaigns."""
    while True:
        try:
            campaigns = await notion_clients.campaigns.get_active_campaigns()
            logger.info(
                "Discovery cycle: found %d active campaigns", len(campaigns)
            )
        except Exception:
            logger.exception("Failed to fetch active campaigns, retrying next cycle")
            await asyncio.sleep(_CYCLE_INTERVAL_SECONDS)
            continue

        for campaign in campaigns:
            try:
                await discover_companies_for_campaign(
                    campaign, config, gemini_client, notion_clients, search_client
                )
            except Exception:
                campaign_name = extract_title(campaign, "Name")
                logger.exception(
                    "Error processing campaign '%s', continuing to next",
                    campaign_name,
                )

        await asyncio.sleep(_CYCLE_INTERVAL_SECONDS)


async def discover_companies_for_campaign(
    campaign: dict,
    config,
    gemini_client: GeminiClient,
    notion_clients: NotionClients,
    search_client: Any,
) -> None:
    """Run the full discovery pipeline for a single campaign."""
    campaign_id = campaign["id"]
    campaign_name = extract_title(campaign, "Name")
    campaign_target = extract_rich_text(campaign, "Target Description")

    if not campaign_target:
        logger.warning(
            "Campaign '%s' has no target description, skipping", campaign_name
        )
        return

    logger.info("Starting discovery for campaign '%s'", campaign_name)

    # -- Step 1: generate search queries via Gemini (one batched call) -------
    queries = await _generate_search_queries(
        gemini_client, config, campaign_target
    )
    if not queries:
        logger.warning(
            "No queries generated for campaign '%s'", campaign_name
        )
        return

    logger.info(
        "Campaign '%s': generated %d search queries", campaign_name, len(queries)
    )

    # -- Step 2: execute searches --------------------------------------------
    all_results = await _execute_searches(search_client, queries)
    if not all_results:
        logger.warning(
            "Campaign '%s': no search results returned", campaign_name
        )
        return

    logger.info(
        "Campaign '%s': collected %d search results across %d queries",
        campaign_name,
        len(all_results),
        len(queries),
    )

    # -- Step 3: parse results via Gemini (one batched call) -----------------
    companies = await _parse_search_results(
        gemini_client, config, campaign_target, all_results
    )
    if not companies:
        logger.info(
            "Campaign '%s': no companies extracted from results", campaign_name
        )
        return

    logger.info(
        "Campaign '%s': extracted %d companies from search results",
        campaign_name,
        len(companies),
    )

    # -- Step 4: dedup and write to Notion -----------------------------------
    new_count, existing_count = await _write_companies(
        notion_clients.companies, companies, campaign_id
    )

    logger.info(
        "Campaign '%s' discovery complete: %d new, %d existing",
        campaign_name,
        new_count,
        existing_count,
    )


async def _generate_search_queries(
    gemini_client: GeminiClient,
    config,
    campaign_target: str,
) -> list[str]:
    """Call Gemini to generate 10-20 search queries for the campaign target."""
    prompt = GENERATE_SEARCH_QUERIES.replace("{campaign_target}", campaign_target)
    result = await gemini_client.generate(
        prompt=prompt,
        user_message=campaign_target,
        model=config.model_discovery,
        json_mode=True,
    )

    text = result["text"].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse query generation response: %s", text[:500])
        return []

    if not isinstance(parsed, list):
        logger.error("Expected JSON array from query generation, got %s", type(parsed))
        return []

    return [q for q in parsed if isinstance(q, str) and q.strip()]


async def _execute_searches(
    search_client: Any,
    queries: list[str],
) -> list[dict]:
    """Execute all search queries and collect results as dicts."""
    all_results: list[dict] = []
    for query in queries:
        try:
            results = await search_client.search(query)
            for r in results:
                all_results.append({
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "source_query": query,
                })
        except Exception:
            logger.exception("Search failed for query: %s", query)
    return all_results


async def _parse_search_results(
    gemini_client: GeminiClient,
    config,
    campaign_target: str,
    results: list[dict],
) -> list[dict]:
    """Call Gemini to extract company names from all collected search results."""
    results_text = json.dumps(results, indent=2)
    prompt = (
        PARSE_SEARCH_RESULTS
        .replace("{campaign_target}", campaign_target)
        .replace("{search_results}", results_text)
    )
    result = await gemini_client.generate(
        prompt=prompt,
        user_message=results_text,
        model=config.model_discovery,
        json_mode=True,
    )

    text = result["text"].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse company extraction response: %s", text[:500])
        return []

    if not isinstance(parsed, list):
        logger.error("Expected JSON array from result parsing, got %s", type(parsed))
        return []

    return [
        c for c in parsed
        if isinstance(c, dict) and c.get("company_name")
    ]


async def _write_companies(
    companies_db: CompaniesDB,
    companies: list[dict],
    campaign_id: str,
) -> tuple[int, int]:
    """
    Write discovered companies to Notion with dedup.

    Returns (new_count, existing_count).
    """
    new_count = 0
    existing_count = 0

    for company in companies:
        name = company.get("company_name", "").strip()
        if not name:
            continue

        website = company.get("website_url", "")
        reasoning = company.get("reasoning", "")

        try:
            existing = await companies_db.find_by_name(name)
            if existing is not None:
                existing_count += 1
                # create_company handles campaign linking for existing records
                await companies_db.create_company(
                    name=name,
                    campaign_id=campaign_id,
                    website=website,
                    source_query=reasoning,
                )
            else:
                result = await companies_db.create_company(
                    name=name,
                    campaign_id=campaign_id,
                    website=website,
                    source_query=reasoning,
                )
                if result is not None:
                    new_count += 1
        except Exception:
            logger.exception("Failed to write company '%s'", name)

    return new_count, existing_count
