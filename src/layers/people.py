"""Layer 3: People discovery worker.

Continuously picks up companies with status "Enriched", discovers
contacts via Google search, generates and verifies email addresses,
and creates contact records in Notion.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from src.discovery.contact_finder import ContactFinder
from src.discovery.email_permutation import EmailPermutator
from src.discovery.smtp_verify import SMTPVerifier
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


def _extract_domain(website_url: str) -> str:
    """Extract the bare domain from a company website URL.

    Handles URLs with or without scheme, strips 'www.' prefix.

    Args:
        website_url: Raw URL string (e.g. "https://www.example.com/about").

    Returns:
        Bare domain string (e.g. "example.com"), or empty string if
        the URL cannot be parsed.
    """
    if not website_url:
        return ""

    url = website_url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _build_contact_body_blocks(
    contact_data: dict,
    company_name: str,
    email: str,
    verified: bool,
) -> list[dict]:
    """Build Notion page body blocks summarising the contact context.

    Args:
        contact_data: Parsed contact dict from Gemini.
        company_name: The company this contact belongs to.
        email: The selected email address.
        verified: Whether the email was verified via SMTP.

    Returns:
        List of Notion block objects for the contact page body.
    """
    verification_label = "Verified" if verified else "Unverified (best guess)"
    lines = [
        f"Contact discovered at {company_name}",
        f"Title: {contact_data.get('title', 'Unknown')}",
        f"Relevance Score: {contact_data.get('relevance_score', 'N/A')}",
        f"Email: {email} ({verification_label})",
    ]
    linkedin = contact_data.get("linkedin_url", "")
    if linkedin:
        lines.append(f"LinkedIn: {linkedin}")

    blocks = []
    for line in lines:
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": line}}]
                },
            }
        )
    return blocks


async def _parse_contacts_with_gemini(
    gemini_client: GeminiClient,
    company_name: str,
    domain: str,
    raw_contacts: list,
) -> list[dict]:
    """Send raw search results through Gemini to extract structured contacts.

    Args:
        gemini_client: The Gemini API client.
        company_name: Name of the target company.
        domain: Company domain.
        raw_contacts: List of RawContact objects from ContactFinder.

    Returns:
        List of parsed contact dicts with name, title, linkedin_url,
        relevance_score fields. Returns empty list on failure.
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


def _split_name(full_name: str) -> tuple[str, str]:
    """Split a full name into first and last name.

    Args:
        full_name: Full name string.

    Returns:
        Tuple of (first_name, last_name). Last name may be empty for
        single-word names.
    """
    parts = full_name.strip().split()
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], " ".join(parts[1:]))


async def _verify_email_waterfall(
    smtp_verifier: SMTPVerifier,
    permutations: list[str],
) -> tuple[str, bool]:
    """Try email permutations in order, stop at first verified.

    Args:
        smtp_verifier: The SMTP verification client.
        permutations: Ordered list of email address candidates.

    Returns:
        Tuple of (email, verified). If none verify, returns the first
        permutation marked as unverified.
    """
    if not permutations:
        return ("", False)

    for email in permutations:
        try:
            result = await smtp_verifier.verify(email)
            if result.valid:
                logger.info("Email verified: %s (method=%s)", email, result.method)
                return (email, True)
        except Exception as exc:
            logger.warning("SMTP verify error for %s: %s", email, exc)
            continue

    # No email verified -- return first permutation as best guess
    return (permutations[0], False)


async def _is_duplicate_contact(
    contacts_db: ContactsDB,
    name: str,
    company_id: str,
) -> bool:
    """Check if a contact with this name already exists for this company.

    Args:
        contacts_db: The Contacts database client.
        name: Contact full name.
        company_id: The Notion page ID of the company.

    Returns:
        True if a matching contact already exists.
    """
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

    Runs the full pipeline: search, parse, dedup, email permutation,
    SMTP verification, and Notion contact creation.

    Args:
        company: Notion page object for the company.
        gemini_client: Gemini API client for parsing search results.
        notion_clients: Aggregate Notion database clients.
        contact_finder: Google-based contact discovery client.
        email_permutator: Email permutation generator.
        smtp_verifier: SMTP email verification client.

    Returns:
        Number of contacts created.
    """
    company_id = company["id"]
    company_name = extract_title(company, "Name")
    website = extract_url(company, "Website")
    domain = _extract_domain(website)
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

    # Step 1: Find contacts via Google search
    raw_contacts = await contact_finder.find_contacts(company_name, domain or "")

    # Step 2: Parse and score via Gemini
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
                first_name, last_name = _split_name(name)
                permutations = email_permutator.generate(
                    first_name, last_name, domain
                )[:3]  # Top 3 patterns only for speed
                if permutations:
                    email, email_verified = await _verify_email_waterfall(
                        smtp_verifier, permutations
                    )

            if email_verified:
                verified_count += 1

            # Build page body
            body_blocks = _build_contact_body_blocks(
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
    """Continuous worker that discovers contacts for enriched companies.

    Polls for companies with status "Enriched", runs the full contact
    discovery pipeline for each, then sleeps before the next cycle.

    Args:
        config: Application configuration.
        gemini_client: Gemini API client.
        notion_clients: Aggregate Notion database clients.
        contact_finder: Google-based contact finder.
        email_permutator: Email permutation generator.
        smtp_verifier: SMTP email verifier.
    """
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
