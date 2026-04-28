"""
Enrichment helper functions: plain text body builder, property updates,
and scrape fallback logic.

Split from enrichment.py to stay under 300-line limit.
"""

import json
import logging
from datetime import datetime, timezone

from src.enrichment.prompts.base import ENRICH_COMPANY

logger = logging.getLogger(__name__)


def build_enrichment_text(result: dict) -> str:
    """Build enrichment report as plain text for the body column."""
    parts: list[str] = []
    parts.append("## Enrichment Report")

    products = result.get("products", [])
    sustainability = result.get("sustainability_focus", False)
    premium = result.get("premium_positioning", False)
    if products or sustainability or premium:
        parts.append("\n## Company Profile")
        if products:
            parts.append(f"Products: {', '.join(products)}")
        if sustainability:
            parts.append("Sustainability Focus: Yes")
        if premium:
            parts.append("Premium Positioning: Yes")

    eu = result.get("eu_presence", "")
    if eu and eu != "Unknown":
        parts.append(f"\n## EU Presence\n{eu}")

    news = result.get("recent_news", "")
    if news and news != "None found":
        parts.append(f"\n## Recent News\n{news}")

    reasoning = result.get("dpp_fit_reasoning", "")
    if reasoning:
        parts.append(f"\n## DPP Fit Assessment\n{reasoning}")

    selling_points = result.get("key_selling_points", [])
    if selling_points:
        parts.append("\n## Key Selling Points")
        for point in selling_points:
            parts.append(f"- {point}")

    summary = result.get("company_summary", "")
    if summary:
        parts.append(f"\n## Summary\n{summary}")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts.append(f"\nEnriched on {now_str}")

    return "\n".join(parts)


def build_properties_update(result: dict, status: str) -> dict:
    """Build a column-name to value dict from an enrichment result."""
    props: dict = {
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

    if "dpp_fit_reasoning" in result:
        props["dpp_fit_reasoning"] = str(result["dpp_fit_reasoning"])

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
