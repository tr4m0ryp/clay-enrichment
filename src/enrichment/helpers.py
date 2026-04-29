"""
Enrichment helper functions: plain text body builder and property updates.

Split from enrichment.py to stay under 300-line limit.
"""

import logging
from datetime import datetime, timezone

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
