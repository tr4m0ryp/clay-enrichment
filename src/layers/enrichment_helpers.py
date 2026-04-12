"""
Enrichment helper functions: Notion block builders, property updates,
and scrape fallback logic.

Split from enrichment.py to stay under 300-line limit.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.notion.prop_helpers import (
    select_prop,
    rich_text_prop,
    number_prop,
    date_prop,
)
from src.prompts.enrichment import ENRICH_COMPANY

logger = logging.getLogger(__name__)


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


def build_enrichment_blocks(result: dict) -> list[dict]:
    """
    Turn a single enrichment result dict into Notion block children
    suitable for append_page_body.
    """
    blocks: list[dict] = []

    blocks.append(_heading("Enrichment Report"))

    # Company profile
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

    # EU presence
    eu_presence = result.get("eu_presence", "")
    if eu_presence and eu_presence != "Unknown":
        blocks.append(_heading("EU Presence"))
        blocks.append(_paragraph(eu_presence))

    # Recent news
    recent_news = result.get("recent_news", "")
    if recent_news and recent_news != "None found":
        blocks.append(_heading("Recent News"))
        blocks.append(_paragraph(recent_news))

    # DPP fit reasoning
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


def build_properties_update(result: dict, status: str) -> dict:
    """Build the Notion property update dict from an enrichment result."""
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


async def scrape_fallback(
    name: str, website: str, campaign_target: str,
    gemini_client, scraper,
) -> dict:
    """Fallback: scrape website and use legacy single-pass prompt."""
    scrape_result = await scraper.scrape_with_fallback(
        company_name=name, primary_url=website,
    ) if website else None

    content = ""
    if scrape_result and scrape_result.content:
        content = scrape_result.content

    prompt = ENRICH_COMPANY.replace(
        "{campaign_target}", campaign_target or "(no campaign target provided)",
    ).replace("{companies}", "(see below)")

    scrape_text = (
        f"Company: {name}\n"
        f"Website: {website}\n\n"
        f"{content if content else '(no content scraped)'}"
    )

    result = await gemini_client.generate(
        prompt=prompt,
        user_message=scrape_text,
        json_mode=True,
    )

    parsed = json.loads(result["text"].strip())
    # Legacy prompt returns an array; take first element
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    return parsed
