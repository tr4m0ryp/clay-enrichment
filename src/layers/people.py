"""Layer 3: People discovery worker.

Continuously picks up companies with status "Enriched", discovers
contacts via SearXNG search, generates and verifies email addresses,
and creates contact records in Notion.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from src.discovery.contact_finder import ContactFinder
from src.discovery.email_permutation import EmailPermutator
from src.discovery.smtp_verify import SMTPVerifier
from src.layers.people_helpers import (
    build_contact_body_blocks,
    extract_domain,
    split_name,
    verify_email_waterfall,
)
from src.models.gemini import GeminiClient
from src.notion.databases_companies import CompaniesDB
from src.notion.databases_contacts import ContactsDB
from src.notion.prop_helpers import (
    extract_title,
    extract_url,
    extract_relation_ids,
    select_prop,
)
from src.prompts.people import PARSE_CONTACT_RESULTS

logger = logging.getLogger(__name__)

_CYCLE_INTERVAL = 180  # seconds between worker cycles


@dataclass
class NotionClients:
    """Aggregate accessor for typed Notion database clients."""

    companies: CompaniesDB
    contacts: ContactsDB


async def _parse_contacts_with_gemini(
    gemini_client: GeminiClient,
    company_name: str,
    domain: str,
    raw_contacts: list,
) -> list[dict]:
    """Parse raw search results via Gemini into structured contact dicts.

    Returns list of dicts with name, title, linkedin_url fields, or
    empty list on failure.
    """
    if not raw_contacts:
        return []

    search_text_parts = []
    for rc in raw_contacts:
        entry = f"Name: {rc.name}"
        if rc.title:
            entry += f", Title: {rc.title}"
        if rc.linkedin_url:
            entry += f", LinkedIn: {rc.linkedin_url}"
        entry += f", Source: {rc.source_url}"
        search_text_parts.append(entry)

    search_results_text = "\n".join(search_text_parts)
    company_context = f"Company: {company_name}\nDomain: {domain}"

    prompt = PARSE_CONTACT_RESULTS.replace(
        "{company_context}", company_context
    ).replace(
        "{search_results}", search_results_text
    )

    try:
        result = await gemini_client.generate(
            prompt=prompt,
            user_message=f"Extract contacts for {company_name}",
            json_mode=True,
        )
        parsed = json.loads(result["text"])
        if isinstance(parsed, list):
            return parsed
        logger.warning("Gemini returned non-list for contacts: %s", type(parsed))
        return []
    except (json.JSONDecodeError, Exception) as exc:
        logger.error("Failed to parse Gemini contact response: %s", exc)
        return []


async def _is_duplicate_contact(
    contacts_db: ContactsDB,
    name: str,
    company_id: str,
) -> bool:
    """Return True if a contact with this name already exists for the company."""
    existing = await contacts_db.get_contacts_for_company(company_id)
    name_lower = name.lower().strip()
    for contact in existing:
        existing_name = extract_title(contact, "Name").lower().strip()
        if existing_name == name_lower:
            return True
    return False


async def discover_contacts_for_company(
    company: dict,
    gemini_client: GeminiClient,
    notion_clients: NotionClients,
    contact_finder: ContactFinder,
    email_permutator: EmailPermutator,
    smtp_verifier: SMTPVerifier,
) -> int:
    """Discover and create contacts for a single company.

    Full pipeline: search, parse, dedup, email permutation, SMTP
    verification, and Notion contact creation. Returns count created.
    """
    company_id = company["id"]
    company_name = extract_title(company, "Name")
    website = extract_url(company, "Website")
    domain = extract_domain(website)
    campaign_ids = extract_relation_ids(company, "Campaign")
    campaign_id = campaign_ids[0] if campaign_ids else ""

    if not company_name:
        logger.warning("Skipping company with no name: %s", company_id)
        return 0

    if not domain:
        logger.warning(
            "No domain for company '%s', skipping email generation",
            company_name,
        )

    logger.info("Discovering contacts for '%s' (domain=%s)", company_name, domain)

    # Step 1: Find contacts via SearXNG search
    raw_contacts = await contact_finder.find_contacts(company_name, domain or "")

    # Step 2: Parse and structure via Gemini
    parsed_contacts = await _parse_contacts_with_gemini(
        gemini_client, company_name, domain or "", raw_contacts
    )

    if not parsed_contacts:
        logger.info("No contacts found for '%s'", company_name)
        await notion_clients.companies.update_company(
            company_id, {"Status": select_prop("Contacts Found")}
        )
        return 0

    # Step 3: Process each contact
    created_count = 0
    verified_count = 0

    for contact_data in parsed_contacts:
        name = contact_data.get("name", "").strip()
        if not name:
            continue

        try:
            # Dedup check
            if await _is_duplicate_contact(
                notion_clients.contacts, name, company_id
            ):
                logger.info("Skipping duplicate contact: %s at %s", name, company_name)
                continue

            title = contact_data.get("title", "")
            linkedin_url = contact_data.get("linkedin_url", "")
            email = ""
            email_verified = False

            # Email permutation + verification waterfall
            if domain:
                first_name, last_name = split_name(name)
                permutations = email_permutator.generate(
                    first_name, last_name, domain
                )[:3]  # Top 3 patterns only for speed
                if permutations:
                    email, email_verified = await verify_email_waterfall(
                        smtp_verifier, permutations
                    )

            if email_verified:
                verified_count += 1

            # Build page body
            body_blocks = build_contact_body_blocks(
                contact_data, company_name, email, email_verified
            )

            # Create contact in Notion
            result = await notion_clients.contacts.create_contact(
                name=name,
                company_id=company_id,
                campaign_id=campaign_id,
                job_title=title,
                email_addr=email,
                email_verified=email_verified,
                linkedin_url=linkedin_url,
                body_blocks=body_blocks,
            )

            if result is not None:
                created_count += 1
                logger.info(
                    "Created contact: %s (%s) at %s | email=%s verified=%s",
                    name, title, company_name, email, email_verified,
                )

        except Exception as exc:
            logger.error(
                "Error processing contact '%s' at '%s': %s",
                name, company_name, exc,
            )
            continue

    # Step 4: Update company status
    await notion_clients.companies.update_company(
        company_id, {"Status": select_prop("Contacts Found")}
    )

    logger.info(
        "Company '%s': %d contacts created, %d emails verified",
        company_name, created_count, verified_count,
    )
    return created_count


async def people_worker(
    config,
    gemini_client: GeminiClient,
    notion_clients: NotionClients,
    contact_finder: ContactFinder,
    email_permutator: EmailPermutator,
    smtp_verifier: SMTPVerifier,
) -> None:
    """Continuous worker: discover contacts for companies with status Enriched."""
    logger.info("People worker started")
    while True:
        try:
            companies = await notion_clients.companies.get_companies_by_status(
                "Enriched"
            )
            logger.info("People worker: found %d enriched companies", len(companies))

            for company in companies:
                try:
                    await discover_contacts_for_company(
                        company,
                        gemini_client,
                        notion_clients,
                        contact_finder,
                        email_permutator,
                        smtp_verifier,
                    )
                except Exception as exc:
                    company_name = extract_title(company, "Name")
                    logger.error(
                        "People worker: error processing '%s': %s",
                        company_name, exc,
                    )

        except Exception as exc:
            logger.error("People worker cycle error: %s", exc)

        await asyncio.sleep(_CYCLE_INTERVAL)
