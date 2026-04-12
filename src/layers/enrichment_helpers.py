"""
Enrichment helper functions: plain text body builders, property updates,
and scrape fallback logic.

Split from enrichment.py to stay under 300-line limit.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.prompts.enrichment import ENRICH_COMPANY

logger = logging.getLogger(__name__)


def build_enrichment_text(result: dict) -> str:
    """
    Turn a single enrichment result dict into plain text suitable
    for storing in the company body column.
    """
    parts: list[str] = []

    parts.append("== Enrichment Report ==")

    # Company profile
    products = result.get("products", [])
    sustainability = result.get("sustainability_focus", False)
    premium = result.get("premium_positioning", False)
    if products or sustainability or premium:
        parts.append("\n-- Company Profile --")
        if products:
            parts.append(f"Products: {', '.join(products)}")
        if sustainability:
            parts.append("Sustainability Focus: Yes")
        if premium:
            parts.append("Premium Positioning: Yes")

    # EU presence
    eu_presence = result.get("eu_presence", "")
    if eu_presence and eu_presence != "Unknown":
        parts.append("\n-- EU Presence --")
        parts.append(eu_presence)

    # Recent news
    recent_news = result.get("recent_news", "")
    if recent_news and recent_news != "None found":
        parts.append("\n-- Recent News --")
        parts.append(recent_news)

    # DPP fit reasoning
    reasoning = result.get("dpp_fit_reasoning", "")
    if reasoning:
        parts.append("\n-- DPP Fit Assessment --")
        parts.append(reasoning)

    # Key selling points
    selling_points = result.get("key_selling_points", [])
    if selling_points:
        parts.append("\n-- Key Selling Points --")
        for point in selling_points:
            parts.append(f"- {point}")

    # Full summary
    summary = result.get("company_summary", "")
    if summary:
        parts.append("\n-- Summary --")
        parts.append(summary)

    # Metadata
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts.append(f"\nEnriched on {now_str}")

    return "\n".join(parts)


def build_properties_update_pg(result: dict, status: str) -> dict:
    """Build a flat column update dict for CompaniesDB.update_company."""
    props: dict[str, Any] = {
        "status": status,
        "last_enriched_at": datetime.now(timezone.utc),
    }

    industry = result.get("industry", "")
    if industry:
        allowed = ("Fashion", "Streetwear", "Lifestyle", "Other")
        props["industry"] = industry if industry in allowed else "Other"

    location = result.get("location", "")
    if location and location != "Unknown":
        props["location"] = location

    size = result.get("size", "")
    if size and size != "Unknown":
        props["size"] = size

    score = result.get("dpp_fit_score")
    if score is not None:
        props["dpp_fit_score"] = int(score)

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
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    return parsed
