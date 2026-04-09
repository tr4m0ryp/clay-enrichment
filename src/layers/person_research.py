"""Layer 3b: Person research worker.

Picks up contacts with status "Enriched", researches each via SearXNG
web search, synthesizes findings via Gemini, and appends structured
research to the contact page body. Updates status to "Researched".
"""

from __future__ import annotations

import asyncio
import json
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
    rich_text_prop,
)
from src.prompts.person_research import RESEARCH_PERSON
from src.search.searxng import SearXNGClient, SearchResult

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


def _deduplicate_results(results: list[SearchResult]) -> list[SearchResult]:
    """Remove duplicate search results by URL, preserving order."""
    seen: set[str] = set()
    unique: list[SearchResult] = []
    for r in results:
        if r.url and r.url not in seen:
            seen.add(r.url)
            unique.append(r)
    return unique


def _format_search_results(results: list[SearchResult]) -> str:
    """Format search results as numbered text for the LLM prompt."""
    if not results:
        return "(no search results found)"
    parts = []
    for i, r in enumerate(results, 1):
        entry = f"[{i}] {r.title}\n    URL: {r.url}"
        if r.snippet:
            entry += f"\n    Snippet: {r.snippet}"
        parts.append(entry)
    return "\n\n".join(parts)


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


def _build_research_blocks(research: dict) -> list[dict]:
    """Build Notion page body blocks from parsed research JSON."""
    blocks: list[dict] = []
    blocks.append(_heading_block("--- Person Research ---"))

    bg = research.get("professional_background", "") or "(no data)"
    blocks.append(_heading_block("Professional Background"))
    blocks.append(_paragraph_block(bg))

    activity = research.get("public_activity", "") or "(no data)"
    blocks.append(_heading_block("Public Activity"))
    blocks.append(_paragraph_block(activity))

    topics = research.get("key_topics", [])
    blocks.append(_heading_block("Key Topics"))
    blocks.append(_paragraph_block(", ".join(topics) if topics else "(none)"))

    signals = research.get("relevance_signals", "") or "(no data)"
    blocks.append(_heading_block("Relevance Signals"))
    blocks.append(_paragraph_block(signals))

    quality = research.get("research_quality", "low")
    blocks.append(_heading_block(f"Research Quality: {quality}"))
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


async def _run_searches(
    search_client: SearXNGClient,
    contact_name: str,
    company_name: str,
    domain: str,
) -> list[SearchResult]:
    """Run SearXNG searches (general, LinkedIn, domain) and deduplicate."""
    general_query = f'"{contact_name}" "{company_name}"'
    linkedin_query = f'"{contact_name}" "{company_name}"'

    tasks = [
        search_client.search(general_query, num_results=10),
        search_client.search_site(
            linkedin_query, "linkedin.com/in", num_results=5
        ),
    ]
    if domain:
        tasks.append(search_client.search(
            f'"{contact_name}" site:{domain}', num_results=5
        ))

    results_lists = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[SearchResult] = []
    for result in results_lists:
        if isinstance(result, Exception):
            logger.warning("Search query failed: %s", result)
            continue
        all_results.extend(result)
    return _deduplicate_results(all_results)


async def _research_contact(
    contact: dict,
    config,
    gemini_client: GeminiClient,
    notion_client: NotionClient,
    contacts_db: ContactsDB,
    search_client: SearXNGClient,
) -> bool:
    """Research a single contact: search, synthesize, store, update status."""
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

    # Run searches and format for prompt
    search_results = await _run_searches(
        search_client, contact_name, company_name, domain
    )
    formatted_results = _format_search_results(search_results)

    # Build prompt using .replace() to avoid conflict with JSON braces
    prompt = (
        RESEARCH_PERSON
        .replace("{contact_name}", contact_name)
        .replace("{contact_title}", job_title or "Unknown")
        .replace("{company_name}", company_name)
        .replace("{company_domain}", domain or "Unknown")
        .replace("{search_results}", formatted_results)
    )

    result = await gemini_client.generate(
        prompt=prompt,
        user_message=f"Research {contact_name} at {company_name}",
        model=config.model_scoring,
        json_mode=True,
    )

    research = json.loads(result["text"])
    quality = research.get("research_quality", "low")
    logger.info(
        "Research for '%s': quality=%s | in=%d out=%d tokens",
        contact_name, quality,
        result["input_tokens"], result["output_tokens"],
    )

    # Append research blocks to contact page body
    await notion_client.append_page_body(
        contact_id, _build_research_blocks(research)
    )

    # Write context_summary to Contact's Context property
    update_props: dict = {"Status": select_prop("Researched")}
    context_summary = research.get("context_summary", "")
    if context_summary:
        update_props["Context"] = rich_text_prop(context_summary)

    # Update Job Title if LLM determined a more accurate role
    determined_role = research.get("determined_role", "")
    if determined_role and determined_role != job_title:
        update_props["Job Title"] = rich_text_prop(determined_role)
        logger.info(
            "Updated job title for '%s': '%s' -> '%s'",
            contact_name, job_title, determined_role,
        )

    await contacts_db.update_contact(contact_id, update_props)
    logger.info("Contact '%s' researched and updated", contact_name)
    return True


async def person_research_worker(
    config,
    gemini_client: GeminiClient,
    notion_client: NotionClient,
    contacts_db: ContactsDB,
    search_client: SearXNGClient,
) -> None:
    """Continuous worker: research enriched contacts via web search + LLM."""
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
                            notion_client, contacts_db, search_client,
                        )
                    except json.JSONDecodeError as exc:
                        name = extract_title(contact, "Name")
                        logger.error(
                            "Failed to parse research for '%s': %s", name, exc
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
