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

import asyncpg

from src.config import Config
from src.db.companies import CompaniesDB
from src.db.contacts import ContactsDB
from src.gemini.client import GeminiClient
from src.people.helpers import extract_domain, split_name
from src.people.pattern_lookup import PatternLookup, construct_email
from src.people.prompts import DISCOVER_CONTACTS
from src.people.published_email_finder import find_published_email
from src.people.smtp_verify import SMTPVerifier
from src.utils.backlog import count_high_priority_backlog
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)

MIN_DPP_FIT_SCORE = 7
_CYCLE_INTERVAL = 300  # 5 min -- bumped from 3 min so the contact-
# discovery pace matches the slowed enrichment+discovery cadence.


@dataclass
class DBClients:
    """Aggregate accessor for typed Postgres database clients."""

    companies: CompaniesDB
    contacts: ContactsDB
    pool: asyncpg.Pool


async def people_worker(
    config: Config,
    gemini_client: GeminiClient,
    db_clients: DBClients,
    smtp_verifier: SMTPVerifier,
) -> None:
    """Continuous loop over Enriched companies above the DPP threshold.

    Backpressure: when the high-priority backlog already exceeds
    ``config.high_priority_backlog_threshold``, contact discovery skips
    the cycle so downstream stages can catch up before more contacts
    enter the funnel. Threshold of 0 disables this.
    """
    threshold = getattr(config, "high_priority_backlog_threshold", 50)
    logger.info(
        "People worker started (backlog_threshold=%d)", threshold,
    )
    pattern_lookup = PatternLookup(config, db_clients.companies)
    while True:
        try:
            if threshold > 0:
                backlog = await count_high_priority_backlog(db_clients.pool)
                if backlog > threshold:
                    logger.info(
                        "People worker: skipping cycle -- high-priority "
                        "backlog=%d exceeds threshold=%d. Resolver + "
                        "email_gen need to drain before discovering more "
                        "contacts.", backlog, threshold,
                    )
                    await asyncio.sleep(_CYCLE_INTERVAL)
                    continue

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

    # Step 1: discover names + titles + LinkedIn via one Gemini call. Email
    # resolution is DEFERRED -- we don't burn Hunter / verifier credits on
    # contacts that may score low. The email_resolver worker picks up
    # contact_campaigns rows with score >= MIN_DPP_FIT_SCORE and resolves
    # only those.
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
    for raw in raw_contacts:
        contact_name = (raw.get("name") or "").strip()
        if not contact_name:
            continue
        # Drop hallucination-signature names: bare initials in the
        # middle ("Anne M. Nielsen") or single-letter trailing tokens
        # ("Beatriz M. S."). Without grounding the model invents these
        # to fill out a roster; they all fail email construction so
        # they're pure noise downstream.
        if _looks_hallucinated(contact_name):
            logger.info(
                "People worker: dropping suspect name '%s' at '%s'",
                contact_name, name,
            )
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
            row = await dbs.contacts.create_contact(
                name=contact_name,
                company_id=company_id,
                campaign_id=campaign_id,
                job_title=(raw.get("title") or "").strip(),
                email_addr="",  # resolved later by email_resolver worker
                email_verified=False,
                # The model cannot reliably know LinkedIn slug URLs
                # (they redirect to dead pages). The prompt forces this
                # to "" but we ALSO drop any value at the worker boundary
                # so a stray non-empty string doesn't pollute the DB.
                linkedin_url="",
            )
            if row is not None:
                created += 1
                logger.info(
                    "People worker: created '%s' (email deferred)",
                    contact_name,
                )
        except Exception:
            logger.exception(
                "People worker: error on contact '%s' at '%s'",
                contact_name, name,
            )

    logger.info("People worker: '%s' -> %d contacts created", name, created)
    await dbs.companies.update_company(
        company_id, {"status": "Contacts Found"},
    )


_SUSPECT_NAME_TOKEN_RE = None


def _looks_hallucinated(name: str) -> bool:
    """Heuristic: drop contact names that match a hallucination signature.

    Without grounding, Gemini fills in unknown roster members with
    plausible-sounding placeholders. Two patterns observed in production
    runs:
      - middle initials: "Anne M. Nielsen", "Carolina M. de la Cruz"
      - trailing single-letter tokens: "Beatriz M. S.", "Irene M. G."
    Both produce broken email constructions (last_word becomes "M." or
    "S."). Reject at the worker boundary so they don't clutter the DB.
    """
    import re
    global _SUSPECT_NAME_TOKEN_RE
    if _SUSPECT_NAME_TOKEN_RE is None:
        # Match: a single-letter uppercase token followed by a period,
        # which appears either between spaces (inline middle initial)
        # or at the end of the string (trailing initial-only token).
        _SUSPECT_NAME_TOKEN_RE = re.compile(
            r"(?:^|\s)[A-Z]\.(?:\s|$)"
        )
    return bool(_SUSPECT_NAME_TOKEN_RE.search(name.strip()))


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
            # No grounding for the same F16 reason as discovery; the
            # company_name + domain pinned in the prompt is enough for
            # the model to recall named decision-makers from training
            # data. Restore once tier-aware fallback lands.
            grounding=False,
            json_mode=True,
            max_retries=30,
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
