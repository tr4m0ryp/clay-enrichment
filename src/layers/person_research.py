"""Layer 3b: Person research worker.

Picks up contacts with status "Enriched", researches each via a single
Gemini call with Google Search grounding, and appends free-text research
to the contact page body. Updates status to "Researched".

Structuring (Context, Job Title, scoring) is handled downstream by
the campaign_scoring layer.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from src.models.gemini import GeminiClient
from src.notion.client import NotionClient
from src.notion.databases_contacts import ContactsDB
from src.notion.prop_helpers import (
    extract_number,
    extract_title,
    extract_rich_text,
    extract_url,
    extract_relation_ids,
    select_prop,
)
from src.prompts.person_research import RESEARCH_PERSON_GROUNDED

logger = logging.getLogger(__name__)

MIN_DPP_FIT_SCORE = 7
_CYCLE_INTERVAL = 180  # seconds between worker cycles
_CONCURRENCY = 5  # max contacts researched in parallel per cycle


def _extract_domain(website_url: str) -> str:
    """Extract bare domain from a URL, stripping www prefix."""
    if not website_url:
        return ""
    url = website_url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    try:
        host = urlparse(url).hostname or ""
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _heading_block(text: str) -> dict:
    """Build a Notion heading_3 block."""
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _paragraph_block(text: str) -> dict:
    """Build a Notion paragraph block (truncated to 2000 chars)."""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}],
        },
    }


def _build_research_blocks(research_text: str) -> list[dict]:
    """Build Notion blocks from free-text grounded research."""
    blocks = [_heading_block("--- Person Research ---")]
    paragraphs = research_text.split("\n\n")
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if para.startswith("## "):
            blocks.append(_heading_block(para.lstrip("# ").strip()))
        else:
            blocks.append(_paragraph_block(para[:2000]))
    return blocks


async def _fetch_company_info(
    notion_client: NotionClient, company_id: str,
) -> tuple[str, str, float | None]:
    """Retrieve company name, domain, and DPP Fit Score from a company page."""
    company_page = await notion_client._call(
        notion_client._sdk.pages.retrieve, page_id=company_id,
    )
    name = extract_title(company_page, "Name")
    website = extract_url(company_page, "Website")
    dpp_score = extract_number(company_page, "DPP Fit Score")
    return name, _extract_domain(website), dpp_score


async def _research_contact(
    contact: dict,
    config,
    gemini_client: GeminiClient,
    notion_client: NotionClient,
    contacts_db: ContactsDB,
) -> bool:
    """Research a single contact: grounded search, store blocks, update status."""
    contact_id = contact["id"]
    contact_name = extract_title(contact, "Name")
    job_title = extract_rich_text(contact, "Job Title")

    # Resolve company from relation
    company_ids = extract_relation_ids(contact, "Company")
    if not company_ids:
        logger.warning(
            "Contact '%s' (%s) has no company relation, skipping",
            contact_name, contact_id,
        )
        return False

    company_name, domain, dpp_score = await _fetch_company_info(
        notion_client, company_ids[0]
    )

    # Gate: skip contacts whose company is below DPP fit score threshold
    if not dpp_score or dpp_score < MIN_DPP_FIT_SCORE:
        logger.info(
            "Skipping research for '%s': company '%s' DPP Fit Score=%s (min=%d)",
            contact_name, company_name, dpp_score, MIN_DPP_FIT_SCORE,
        )
        return False

    logger.info(
        "Researching '%s' (%s) at '%s'",
        contact_name, job_title, company_name,
    )

    # Build prompt using .replace() to avoid conflict with braces
    prompt = (
        RESEARCH_PERSON_GROUNDED
        .replace("{contact_name}", contact_name)
        .replace("{contact_title}", job_title or "Unknown")
        .replace("{company_name}", company_name)
        .replace("{company_domain}", domain or "Unknown")
    )

    result = await gemini_client.generate(
        prompt=prompt,
        user_message=f"Research {contact_name} at {company_name}",
        model=config.model_research,
        grounding=True,
    )

    research_text = result["text"]
    logger.info(
        "Research for '%s': in=%d out=%d tokens",
        contact_name, result["input_tokens"], result["output_tokens"],
    )

    # Append research blocks to contact page body
    blocks = _build_research_blocks(research_text)
    await notion_client.append_page_body(contact_id, blocks)

    # Update status only -- Context and Job Title are set by campaign_scoring
    await contacts_db.update_contact(
        contact_id, {"Status": select_prop("Researched")}
    )
    logger.info("Contact '%s' researched and updated", contact_name)
    return True


async def person_research_worker(
    config,
    gemini_client: GeminiClient,
    notion_client: NotionClient,
    contacts_db: ContactsDB,
) -> None:
    """Continuous worker: research enriched contacts via grounded Gemini call."""
    logger.info("Person research worker started")
    while True:
        try:
            filter_obj = {
                "property": "Status",
                "select": {"equals": "Enriched"},
            }
            contacts = await notion_client.query_database(
                contacts_db.db_id, filter_obj
            )
            logger.info(
                "Person research: found %d enriched contacts", len(contacts),
            )

            sem = asyncio.Semaphore(_CONCURRENCY)

            async def _bounded(contact: dict) -> None:
                async with sem:
                    try:
                        await _research_contact(
                            contact, config, gemini_client,
                            notion_client, contacts_db,
                        )
                    except Exception as exc:
                        name = extract_title(contact, "Name")
                        logger.error(
                            "Error researching contact '%s': %s", name, exc
                        )

            await asyncio.gather(*[_bounded(c) for c in contacts])

        except Exception as exc:
            logger.error("Person research worker cycle error: %s", exc)

        await asyncio.sleep(_CYCLE_INTERVAL)
