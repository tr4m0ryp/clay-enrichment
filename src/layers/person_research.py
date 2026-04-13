"""Layer 3b: Person research worker.

Picks up contacts with status "Enriched", researches each via a single
Gemini call with Google Search grounding, and stores free-text research
in the contact body column. Updates status to "Researched".

Structuring (Context, Job Title, scoring) is handled downstream by
the campaign_scoring layer.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse
from uuid import UUID

from src.db.companies import CompaniesDB
from src.db.contacts import ContactsDB
from src.discovery.title_filter import is_relevant_title
from src.models.gemini import GeminiClient
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


async def _fetch_company_info(
    companies_db: CompaniesDB, company_id: str,
) -> tuple[str, str, float | None]:
    """Retrieve company name, domain, and DPP Fit Score from the DB."""
    rows = await companies_db._pool.fetch(
        "SELECT name, website, dpp_fit_score FROM companies WHERE id = $1",
        UUID(company_id),
    )
    if not rows:
        return "", "", None
    row = rows[0]
    return row["name"] or "", _extract_domain(row["website"] or ""), row["dpp_fit_score"]


async def _research_contact(
    contact: dict,
    config,
    gemini_client: GeminiClient,
    contacts_db: ContactsDB,
    companies_db: CompaniesDB,
) -> bool:
    """Research a single contact: grounded search, store body, update status."""
    contact_id = str(contact["id"])
    contact_name = contact.get("name") or ""
    job_title = contact.get("job_title") or ""

    # Gate: skip contacts with irrelevant or empty titles
    if not is_relevant_title(job_title):
        logger.info(
            "Skipping research for '%s': title '%s' not relevant",
            contact_name, job_title,
        )
        return False

    # Resolve company from direct FK
    company_id = contact.get("company_id")
    if not company_id:
        logger.warning(
            "Contact '%s' (%s) has no company, skipping",
            contact_name, contact_id,
        )
        return False

    company_name, domain, dpp_score = await _fetch_company_info(
        companies_db, str(company_id),
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

    # Store research text in contact body column
    await contacts_db.set_body(contact_id, research_text)

    # Update status to Researched
    await contacts_db.update_contact(contact_id, status="Researched")
    logger.info("Contact '%s' researched and updated", contact_name)
    return True


async def person_research_worker(
    config,
    gemini_client: GeminiClient,
    contacts_db: ContactsDB,
    companies_db: CompaniesDB,
) -> None:
    """Continuous worker: research enriched contacts via grounded Gemini call."""
    logger.info("Person research worker started")
    while True:
        try:
            contacts = await contacts_db.get_contacts_by_status("Enriched")
            logger.info(
                "Person research: found %d enriched contacts", len(contacts),
            )

            sem = asyncio.Semaphore(_CONCURRENCY)

            async def _bounded(contact: dict) -> None:
                async with sem:
                    try:
                        await _research_contact(
                            contact, config, gemini_client,
                            contacts_db, companies_db,
                        )
                    except Exception as exc:
                        name = contact.get("name", "?")
                        logger.error(
                            "Error researching contact '%s': %s", name, exc
                        )

            await asyncio.gather(*[_bounded(c) for c in contacts])

        except Exception as exc:
            logger.error("Person research worker cycle error: %s", exc)

        await asyncio.sleep(_CYCLE_INTERVAL)
