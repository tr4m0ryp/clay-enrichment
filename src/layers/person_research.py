"""Layer 3b: Person research worker.

Picks up contacts with status "Enriched", researches each via a single
Gemini call with Google Search grounding, and appends free-text research
to the contact body column. Updates status to "Researched".

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
    """Retrieve company name, domain, and DPP Fit Score from a company row."""
    row = await companies_db._pool.fetchrow(
        "SELECT name, website, dpp_fit_score FROM companies WHERE id = $1",
        UUID(company_id),
    )
    if not row:
        return "", "", None
    name = row["name"] or ""
    website = row["website"] or ""
    dpp_score = row["dpp_fit_score"]
    return name, _extract_domain(website), dpp_score


async def _research_contact(
    contact: dict,
    config,
    gemini_client: GeminiClient,
    contacts_db: ContactsDB,
    companies_db: CompaniesDB,
) -> bool:
    """Research a single contact: grounded search, store body, update status."""
    contact_id = str(contact["id"])
    contact_name = contact.get("name", "")
    job_title = contact.get("job_title", "") or ""

    # Resolve company from company_id column
    company_id = contact.get("company_id")
    if not company_id:
        logger.warning(
            "Contact '%s' (%s) has no company_id, skipping",
            contact_name, contact_id,
        )
        return False

    company_name, domain, dpp_score = await _fetch_company_info(
        companies_db, str(company_id)
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

    # Format and append research to contact body
    body_text = f"--- Person Research ---\n\n{research_text}"
    existing_body = await contacts_db.get_body(contact_id)
    if existing_body:
        new_body = f"{existing_body}\n\n{body_text}"
    else:
        new_body = body_text
    await contacts_db.set_body(contact_id, new_body)

    # Update status
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
            # Query contacts with status = 'Enriched' directly via SQL
            rows = await contacts_db._pool.fetch(
                "SELECT * FROM contacts WHERE status = $1 "
                "ORDER BY created_at",
                "Enriched",
            )
            contacts = [dict(r) for r in rows]
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
                        name = contact.get("name", "unknown")
                        logger.error(
                            "Error researching contact '%s': %s", name, exc
                        )

            await asyncio.gather(*[_bounded(c) for c in contacts])

        except Exception as exc:
            logger.error("Person research worker cycle error: %s", exc)

        await asyncio.sleep(_CYCLE_INTERVAL)
