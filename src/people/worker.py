"""People worker -- single-call Gemini grounded discovery + new email pipeline.

Per research F14: discover contacts via one Gemini grounded structured
call; per company ensure the email pattern is cached (pattern_lookup);
per contact try published_email_finder (Gemini grounded) first, then
construct from the cached pattern; SMTP verify exactly one email per
contact; no permutator, no waterfall.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from src.config import Config
from src.db.companies import CompaniesDB
from src.db.contacts import ContactsDB
from src.gemini.client import GeminiClient
from src.people.helpers import extract_domain, split_name
from src.people.pattern_lookup import PatternLookup, construct_email
from src.people.prompts import DISCOVER_CONTACTS
from src.people.published_email_finder import find_published_email
from src.people.smtp_verify import SMTPVerifier
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)

MIN_DPP_FIT_SCORE = 7
_CYCLE_INTERVAL = 180  # seconds between worker cycles


@dataclass
class DBClients:
    """Aggregate accessor for typed Postgres database clients."""

    companies: CompaniesDB
    contacts: ContactsDB


async def people_worker(
    config: Config,
    gemini_client: GeminiClient,
    db_clients: DBClients,
    smtp_verifier: SMTPVerifier,
) -> None:
    """Continuous loop over Enriched companies above the DPP threshold."""
    logger.info("People worker started")
    pattern_lookup = PatternLookup(config, db_clients.companies)
    while True:
        try:
            companies = await db_clients.companies.get_companies_by_status(
                "Enriched",
            )
            logger.info("People worker: %d enriched companies", len(companies))
            for company in companies:
                score = company.get("dpp_fit_score") or 0
                if score < MIN_DPP_FIT_SCORE:
                    logger.info(
                        "People worker: skipping '%s' (DPP=%s, min=%d)",
                        company.get("name", "?"), score, MIN_DPP_FIT_SCORE,
                    )
                    continue
                try:
                    await _process_company(
                        company, gemini_client, db_clients,
                        pattern_lookup, smtp_verifier,
                    )
                except Exception:
                    logger.exception(
                        "People worker: error on '%s'",
                        company.get("name", "?"),
                    )
        except Exception:
            logger.exception("People worker cycle error")
        await asyncio.sleep(_CYCLE_INTERVAL)


async def _process_company(
    company: dict,
    gemini_client: GeminiClient,
    dbs: DBClients,
    pattern_lookup: PatternLookup,
    smtp_verifier: SMTPVerifier,
) -> None:
    """Discover contacts for one company, resolve emails, persist rows."""
    company_id = str(company["id"])
    name = (company.get("name") or "").strip()
    domain = extract_domain(company.get("website") or "")
    cids = await dbs.companies.get_campaign_ids(company_id)
    campaign_id = cids[0] if cids else ""

    if not name or not domain:
        logger.info(
            "People worker: skipping '%s' (no name or domain)",
            name or company_id,
        )
        await dbs.companies.update_company(
            company_id, {"status": "Contacts Found"},
        )
        return

    logger.info("People worker: processing '%s' (domain=%s)", name, domain)

    # Step 1: ensure email pattern is cached on the companies row.
    pattern, src = await pattern_lookup.get_pattern(company_id, domain)
    logger.info(
        "People worker: pattern for %s -> %r (source=%s)", domain, pattern, src,
    )

    # Step 2: one Gemini grounded structured call -> contact list.
    raw_contacts = await _discover_contacts(gemini_client, name, domain)
    if not raw_contacts:
        logger.info("People worker: no contacts found for '%s'", name)
        await dbs.companies.update_company(
            company_id, {"status": "Contacts Found"},
        )
        return

    # Dedup against contacts already on file for this company.
    existing = await dbs.contacts.get_contacts_for_company(company_id)
    seen = {
        (c.get("name") or "").strip().lower()
        for c in existing if c.get("name")
    }

    created = 0
    verified = 0
    for raw in raw_contacts:
        contact_name = (raw.get("name") or "").strip()
        if not contact_name:
            continue
        key = contact_name.lower()
        if key in seen:
            logger.info(
                "People worker: skipping duplicate '%s' at '%s'",
                contact_name, name,
            )
            continue
        seen.add(key)
        try:
            persisted, was_verified = await _resolve_and_persist_contact(
                raw,
                company_id=company_id,
                campaign_id=campaign_id,
                company_name=name,
                domain=domain,
                pattern=pattern,
                gemini_client=gemini_client,
                contacts_db=dbs.contacts,
                smtp_verifier=smtp_verifier,
            )
            created += int(persisted)
            verified += int(was_verified)
        except Exception:
            logger.exception(
                "People worker: error on contact '%s' at '%s'",
                contact_name, name,
            )

    logger.info(
        "People worker: '%s' -> %d created, %d verified",
        name, created, verified,
    )
    await dbs.companies.update_company(
        company_id, {"status": "Contacts Found"},
    )


async def _discover_contacts(
    gemini_client: GeminiClient,
    company_name: str,
    domain: str,
) -> list[dict]:
    """One Gemini grounded structured call -> list of contact dicts.

    Returns ``{"name", "title", "linkedin_url"}`` dicts; empty list on
    parse failure or non-list payload. ``{campaign_target}`` is rendered
    as ``""`` -- the caller does not thread it through.
    """
    rendered = (
        DISCOVER_CONTACTS
        .replace("{company_name}", company_name)
        .replace("{domain}", domain)
        .replace("{campaign_target}", "")
    )

    async def _call(user_message: str) -> dict:
        return await gemini_client.generate(
            prompt=rendered,
            user_message=user_message,
            grounding=True,
            json_mode=True,
        )

    base = f"Find decision-makers at {company_name} ({domain})."
    try:
        result = await retry_on_malformed_json(_call, base)
    except Exception:
        logger.exception(
            "People worker: discover_contacts call failed for %s", domain,
        )
        return []
    if result is None:
        return []
    parsed, _raw = result
    if not isinstance(parsed, list):
        logger.warning(
            "People worker: discover_contacts non-list for %s: %s",
            domain, type(parsed).__name__,
        )
        return []
    return [c for c in parsed if isinstance(c, dict) and c.get("name")]


async def _resolve_and_persist_contact(
    raw_contact: dict,
    *,
    company_id: str,
    campaign_id: str,
    company_name: str,
    domain: str,
    pattern: str,
    gemini_client: GeminiClient,
    contacts_db: ContactsDB,
    smtp_verifier: SMTPVerifier,
) -> tuple[bool, bool]:
    """Resolve one contact's email + SMTP probe + persist row.

    Returns ``(persisted, verified)``: ``persisted`` is False when
    ``create_contact``'s email dedup skipped the row; ``verified`` is
    True only when the SMTP probe came back valid.
    """
    name = (raw_contact.get("name") or "").strip()
    title = (raw_contact.get("title") or "").strip()
    linkedin_url = (raw_contact.get("linkedin_url") or "").strip()
    first, last = split_name(name)

    email, src = await _resolve_email(
        gemini_client, first, last, domain, company_name, pattern,
    )

    verified = False
    if email:
        try:
            result = await smtp_verifier.verify(email)
            verified = bool(getattr(result, "valid", False))
        except Exception:
            logger.exception("People worker: SMTP verify failed for %s", email)
    else:
        logger.info(
            "People worker: no email for '%s' at %s; storing unverified",
            name, domain,
        )

    row = await contacts_db.create_contact(
        name=name,
        company_id=company_id,
        campaign_id=campaign_id,
        job_title=title,
        email_addr=email,
        email_verified=verified,
        linkedin_url=linkedin_url,
    )
    persisted = row is not None
    if persisted:
        logger.info(
            "People worker: created '%s' (source=%s verified=%s)",
            name, src or "none", verified,
        )
    return persisted, verified


async def _resolve_email(
    gemini_client: GeminiClient,
    first: str,
    last: str,
    domain: str,
    company_name: str,
    pattern: str,
) -> tuple[str, str]:
    """Return ``(email, source)``; ``source=""`` when both lookups miss."""
    try:
        published, _conf = await find_published_email(
            gemini_client, first, last, domain, company_name,
        )
    except Exception:
        logger.exception(
            "People worker: published_email_finder failed for %s %s @ %s",
            first, last, domain,
        )
        published = ""
    if published:
        return published, "gemini"
    if pattern:
        constructed = construct_email(pattern, first, last, domain)
        if constructed:
            return constructed, "pattern"
    return "", ""
