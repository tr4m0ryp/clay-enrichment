"""
Layer 2: Company enrichment worker.

Continuous async loop that picks up Discovered and stale companies,
scrapes their websites (with fallback), runs single-pass AI enrichment
and DPP scoring in batches of 3, then writes structured results back
to Notion (properties + page body report).
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from src.notion.prop_helpers import (
    select_prop,
    rich_text_prop,
    number_prop,
    date_prop,
    extract_title,
    extract_url,
    extract_rich_text,
    extract_relation_ids,
)
from src.prompts.enrichment import ENRICH_COMPANY

logger = logging.getLogger(__name__)

BATCH_SIZE = 3
CYCLE_SLEEP_SECONDS = 120


def chunk(items: list, size: int = BATCH_SIZE) -> list[list]:
    """Split a list into sublists of at most *size* elements."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _build_enrichment_blocks(result: dict) -> list[dict]:
    """
    Turn a single enrichment result dict into Notion block children
    suitable for append_page_body.

    Produces a heading, key facts, DPP scoring, selling points, and
    the full company summary -- all as simple paragraph/heading blocks.
    """
    blocks: list[dict] = []

    def _heading(text: str) -> dict:
        return {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": text}}]
            },
        }

    def _paragraph(text: str) -> dict:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": text[:2000]}}]
            },
        }

    def _bullet(text: str) -> dict:
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": text[:2000]}}]
            },
        }

    blocks.append(_heading("Enrichment Report"))

    # Company details not stored as properties
    products = result.get("products", [])
    sustainability = result.get("sustainability_focus", False)
    premium = result.get("premium_positioning", False)
    if products or sustainability or premium:
        blocks.append(_heading("Company Profile"))
        if products:
            blocks.append(_bullet(f"Products: {', '.join(products)}"))
        if sustainability:
            blocks.append(_bullet("Sustainability Focus: Yes"))
        if premium:
            blocks.append(_bullet("Premium Positioning: Yes"))

    # DPP fit reasoning (score itself is stored as a property)
    reasoning = result.get("dpp_fit_reasoning", "")
    if reasoning:
        blocks.append(_heading("DPP Fit Assessment"))
        blocks.append(_paragraph(reasoning))

    # Key selling points
    selling_points = result.get("key_selling_points", [])
    if selling_points:
        blocks.append(_heading("Key Selling Points"))
        for point in selling_points:
            blocks.append(_bullet(point))

    # Full summary
    summary = result.get("company_summary", "")
    if summary:
        blocks.append(_heading("Summary"))
        blocks.append(_paragraph(summary))

    # Metadata
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    blocks.append(_paragraph(f"Enriched on {now_str}"))

    return blocks


def _build_properties_update(result: dict, status: str) -> dict:
    """
    Build the Notion property update dict from an enrichment result.
    """
    props: dict[str, Any] = {
        "Status": select_prop(status),
        "Last Enriched": date_prop(),
    }

    industry = result.get("industry", "")
    if industry:
        allowed = ("Fashion", "Streetwear", "Lifestyle", "Other")
        props["Industry"] = select_prop(industry if industry in allowed else "Other")

    location = result.get("location", "")
    if location and location != "Unknown":
        props["Location"] = rich_text_prop(location)

    size = result.get("size", "")
    if size and size != "Unknown":
        props["Size"] = rich_text_prop(size)

    score = result.get("dpp_fit_score")
    if score is not None:
        props["DPP Fit Score"] = number_prop(int(score))

    return props


def _build_scrape_text(company_page: dict, scrape_result) -> str:
    """
    Format scraped content for a company, ready for the Gemini prompt.
    """
    name = extract_title(company_page, "Name")
    website = extract_url(company_page, "Website")
    content = scrape_result.content if scrape_result.content else "(no content scraped)"

    return (
        f"Company: {name}\n"
        f"Website: {website}\n"
        f"Source: {scrape_result.source_url}\n"
        f"Primary site available: {scrape_result.is_primary}\n\n"
        f"{content}"
    )


async def _scrape_company(company_page: dict, scraper) -> Any:
    """Scrape a single company, returning the ScrapeResult."""
    name = extract_title(company_page, "Name")
    website = extract_url(company_page, "Website")

    if not website:
        logger.warning("Company '%s' has no website URL, skipping scrape", name)
        return None

    return await scraper.scrape_with_fallback(
        company_name=name,
        primary_url=website,
    )


async def _get_campaign_target(company_page: dict, campaigns_db) -> str:
    """
    Retrieve the campaign target description for a company.

    Falls back to an empty string if the campaign cannot be resolved.
    """
    campaign_ids = extract_relation_ids(company_page, "Campaign")
    if not campaign_ids:
        return ""

    try:
        campaigns = await campaigns_db.get_processable_campaigns()
        for campaign in campaigns:
            if campaign["id"] in campaign_ids:
                return extract_rich_text(campaign, "Target Description")
    except Exception as exc:
        logger.warning("Failed to fetch campaign target: %s", exc)

    return ""


async def enrich_batch(
    batch: list[dict],
    config,
    gemini_client,
    notion_client,
    companies_db,
    campaigns_db,
    scraper,
) -> None:
    """
    Enrich a batch of company pages.

    1. Scrape all company websites in parallel.
    2. Combine scraped content into one Gemini batch call.
    3. Parse structured results and update Notion for each company.
    """
    if not batch:
        return

    # Step 1: scrape websites in parallel
    scrape_tasks = [_scrape_company(page, scraper) for page in batch]
    scrape_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

    # Build items for the Gemini batch call
    items: list[str] = []
    valid_indices: list[int] = []
    scrape_map: dict[int, Any] = {}

    for idx, (page, scrape_result) in enumerate(zip(batch, scrape_results)):
        name = extract_title(page, "Name")

        if isinstance(scrape_result, Exception):
            logger.error("Scrape failed for '%s': %s", name, scrape_result)
            scrape_map[idx] = None
            continue

        if scrape_result is None:
            logger.warning("No scrape result for '%s' (no website)", name)
            scrape_map[idx] = None
            continue

        scrape_map[idx] = scrape_result
        items.append(_build_scrape_text(page, scrape_result))
        valid_indices.append(idx)

    if not items:
        # All scrapes failed -- mark all as Partially Enriched
        for page in batch:
            name = extract_title(page, "Name")
            try:
                await companies_db.update_company(
                    page["id"],
                    {
                        "Status": select_prop("Partially Enriched"),
                        "Last Enriched": date_prop(),
                    },
                )
                logger.info("Marked '%s' as Partially Enriched (no data)", name)
            except Exception as exc:
                logger.error("Failed to update '%s': %s", name, exc)
        return

    # Step 2: get campaign target for prompt formatting
    campaign_target = await _get_campaign_target(batch[0], campaigns_db)
    prompt = ENRICH_COMPANY.replace(
        "{campaign_target}", campaign_target or "(no campaign target provided)"
    ).replace(
        "{companies}", "(see items below)"
    )

    # Step 3: call Gemini
    try:
        gemini_response = await gemini_client.generate_batch(
            prompt=prompt,
            items=items,
            json_mode=True,
        )
    except Exception as exc:
        logger.error("Gemini batch call failed: %s", exc)
        for page in batch:
            name = extract_title(page, "Name")
            try:
                await companies_db.update_company(
                    page["id"],
                    {
                        "Status": select_prop("Partially Enriched"),
                        "Last Enriched": date_prop(),
                    },
                )
            except Exception as update_exc:
                logger.error("Failed to update '%s': %s", name, update_exc)
        return

    results_list = gemini_response.get("results", [])
    logger.info(
        "Gemini enrichment: %d results, in=%d out=%d tokens",
        len(results_list),
        gemini_response.get("input_tokens", 0),
        gemini_response.get("output_tokens", 0),
    )

    # Step 4: apply results to each company
    for result_idx, batch_idx in enumerate(valid_indices):
        page = batch[batch_idx]
        name = extract_title(page, "Name")
        scrape_result = scrape_map[batch_idx]

        if result_idx >= len(results_list):
            logger.warning("No Gemini result for '%s' (index out of range)", name)
            try:
                await companies_db.update_company(
                    page["id"],
                    {
                        "Status": select_prop("Partially Enriched"),
                        "Last Enriched": date_prop(),
                    },
                )
            except Exception as exc:
                logger.error("Failed to update '%s': %s", name, exc)
            continue

        result = results_list[result_idx]
        is_partial = scrape_result is not None and scrape_result.partial
        status = "Partially Enriched" if is_partial else "Enriched"

        try:
            properties = _build_properties_update(result, status)
            await companies_db.update_company(page["id"], properties)

            blocks = _build_enrichment_blocks(result)
            await notion_client.append_page_body(page["id"], blocks)

            score = result.get("dpp_fit_score", "N/A")
            logger.info(
                "Enriched '%s': score=%s status=%s", name, score, status
            )
        except Exception as exc:
            logger.error("Failed to update Notion for '%s': %s", name, exc)

    # Mark any companies that had no scrape data at all
    for idx, page in enumerate(batch):
        if idx not in valid_indices:
            name = extract_title(page, "Name")
            try:
                await companies_db.update_company(
                    page["id"],
                    {
                        "Status": select_prop("Partially Enriched"),
                        "Last Enriched": date_prop(),
                    },
                )
                logger.info("Marked '%s' as Partially Enriched (scrape failed)", name)
            except Exception as exc:
                logger.error("Failed to update '%s': %s", name, exc)


async def enrichment_worker(
    config,
    gemini_client,
    notion_client,
    companies_db,
    campaigns_db,
    scraper,
) -> None:
    """
    Continuous worker loop: picks up Discovered and stale companies,
    enriches them in batches of 3.

    Runs indefinitely, sleeping CYCLE_SLEEP_SECONDS between cycles.
    """
    logger.info("Enrichment worker started")

    while True:
        try:
            companies = await companies_db.get_companies_by_status("Discovered")
            stale = await companies_db.get_stale_companies(config.enrichment_stale_days)
            companies.extend(stale)

            # Deduplicate by page ID (stale might overlap with Discovered)
            seen_ids: set[str] = set()
            unique: list[dict] = []
            for c in companies:
                pid = c["id"]
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    unique.append(c)

            if unique:
                logger.info("Enrichment cycle: %d companies to process", len(unique))
                for batch in chunk(unique, size=BATCH_SIZE):
                    await enrich_batch(
                        batch,
                        config,
                        gemini_client,
                        notion_client,
                        companies_db,
                        campaigns_db,
                        scraper,
                    )
            else:
                logger.debug("Enrichment cycle: no companies to process")

        except Exception as exc:
            logger.error("Enrichment cycle error: %s", exc)

        await asyncio.sleep(CYCLE_SLEEP_SECONDS)
