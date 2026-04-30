"""Email resolver worker -- runs only on high-priority leads.

Polls contact_campaigns where relevance_score >= MIN_RESOLVE_SCORE and
the contact has no email yet, resolves the email (Hunter pattern +
construct + MyEmailVerifier), persists back to contacts.email +
contact_campaigns.email + email_verified flag.

Deferred to scoring time so we don't spend Hunter quota / verification
credits on contacts that ultimately score too low to email. Per the
2026-04-30 architectural change, the people worker no longer constructs
or verifies emails -- that's the resolver's job, gated by the score
threshold.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import asyncpg

from src.config import Config
from src.db.companies import CompaniesDB
from src.db.contacts import ContactsDB
from src.people.helpers import extract_domain, split_name
from src.people.pattern_lookup import PatternLookup, construct_email

logger = logging.getLogger(__name__)

MIN_RESOLVE_SCORE = 7  # mirrors MIN_DPP_FIT_SCORE used elsewhere
_CYCLE_INTERVAL_SECONDS = 180
_CONCURRENCY = 3


@dataclass
class DBClients:
    """Aggregate of DB handles the resolver needs."""

    companies: CompaniesDB
    contacts: ContactsDB
    pool: asyncpg.Pool


async def _fetch_resolvable_pairs(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Pairs (contact_campaigns row + contact + company) needing email resolution.

    Joins for efficiency: one query gives us the whole context the
    worker needs per row, plus filters out anything already resolved.
    """
    # Match on missing email only -- the LinkedIn URL is captured as a
    # side-effect of the Hunter Email Finder call so a single credit
    # resolves both. Adding `OR linkedin_url IS NULL` would cause
    # contacts where Hunter genuinely has no LinkedIn slug to be
    # re-fetched every cycle, burning credits indefinitely. Existing
    # already-resolved leads are backfilled by a one-shot script
    # (scripts/backfill_linkedin.py) instead.
    sql = """
        SELECT
            cc.id           AS junction_id,
            cc.contact_id,
            cc.campaign_id,
            cc.company_id,
            cc.relevance_score,
            c.name          AS contact_name,
            c.job_title,
            co.name         AS company_name,
            co.website      AS company_website,
            co.email_pattern,
            co.email_pattern_source
        FROM contact_campaigns cc
        JOIN contacts c   ON cc.contact_id = c.id
        LEFT JOIN companies co ON cc.company_id = co.id
        WHERE cc.relevance_score >= $1
          AND (c.email IS NULL OR c.email = '')
        ORDER BY cc.relevance_score DESC, cc.created_at ASC
        LIMIT 50
    """
    async with pool.acquire() as conn:
        return await conn.fetch(sql, MIN_RESOLVE_SCORE)


async def _resolve_one(
    row: asyncpg.Record,
    pattern_lookup: PatternLookup,
    smtp_verifier: Any,
    dbs: DBClients,
) -> tuple[str, bool, str, str]:
    """Resolve one (contact, campaign) pair.

    Returns ``(email, verified, source, linkedin_url)``. ``email`` is
    the address to persist (may be ``""`` when nothing valid was
    produced). ``verified`` reflects the verifier's verdict. ``source``
    is one of ``"pattern"``, ``"finder(score=N)"``, ``"none"``.
    ``linkedin_url`` is the LinkedIn slug URL Hunter associated with
    this contact (empty string when Hunter had none or wasn't called).
    """
    contact_name = row["contact_name"] or ""
    company_name = row["company_name"] or ""
    website = row["company_website"] or ""
    domain = extract_domain(website)

    if not contact_name or not domain:
        return "", False, "none", ""

    first, last = split_name(contact_name)

    # 1. Hunter Email Finder -- returns the actual indexed address (or
    # Hunter's high-confidence construction) plus the verified LinkedIn
    # URL Hunter associated with this contact (when known). Costs 1
    # credit but is far more accurate than blindly applying a pattern.
    # Threshold guards against low-confidence Hunter guesses.
    found_email, find_score, linkedin_url = await pattern_lookup.find_email(
        domain, first, last,
    )
    if found_email:
        verified = await _verify(found_email, smtp_verifier)
        if verified:
            return (
                found_email, True, f"finder(score={find_score})",
                linkedin_url,
            )
        # Hunter's address looked confident but didn't actually accept.
        # Surprisingly common -- Hunter's "score" is calibrated against
        # public-source recall, not real-time SMTP. Continue to pattern
        # construction as fallback so we don't drop the contact entirely.
        logger.info(
            "email_resolver: Hunter Finder address %s did not verify; "
            "falling back to pattern", found_email,
        )

    # 2. Pattern lookup (cached per company; one Hunter credit max per
    # company, regardless of how many contacts it has).
    pattern = (row["email_pattern"] or "").strip()
    pattern_source = (row["email_pattern_source"] or "").strip()
    if not pattern and pattern_source != "none":
        company_id = str(row["company_id"]) if row["company_id"] else ""
        if company_id:
            pattern, src = await pattern_lookup.get_pattern(company_id, domain)
            pattern_source = src
            logger.info(
                "email_resolver: pattern for %s -> %r (source=%s)",
                domain, pattern, src,
            )

    if not pattern:
        return "", False, "none", linkedin_url

    candidate = construct_email(pattern, first, last, domain)
    if not candidate:
        return "", False, "none", linkedin_url

    verified = await _verify(candidate, smtp_verifier)
    return candidate, verified, "pattern", linkedin_url


async def _verify(email: str, smtp_verifier: Any) -> bool:
    """Run the verifier; swallow exceptions so one bad call doesn't crash."""
    try:
        result = await smtp_verifier.verify(email)
    except Exception:
        logger.exception("email_resolver: verify call raised for %s", email)
        return False
    return bool(getattr(result, "valid", False))


async def _persist_resolution(
    row: asyncpg.Record,
    email: str,
    verified: bool,
    linkedin_url: str,
    dbs: DBClients,
) -> None:
    """Update contacts + contact_campaigns with email and LinkedIn URL.

    ``linkedin_url`` is written through to BOTH tables so the leads_full
    view (which joins on cc.linkedin_url) shows real, working profile
    links instead of empty cells. An empty string leaves the existing
    column untouched -- we never blank a value the model previously
    populated through some other path.
    """
    contact_id = str(row["contact_id"])
    junction_id = str(row["junction_id"])

    if email or linkedin_url:
        contact_fields: dict[str, Any] = {}
        if email:
            contact_fields["email"] = email
            contact_fields["email_verified"] = verified
        if linkedin_url:
            contact_fields["linkedin_url"] = linkedin_url
        try:
            await dbs.contacts.update_contact(contact_id, **contact_fields)
        except Exception:
            logger.exception(
                "email_resolver: failed to update contact %s", contact_id,
            )

    # Build the junction UPDATE dynamically so an empty linkedin_url
    # doesn't overwrite a populated one.
    set_clauses = ["email = $1", "email_verified = $2", "updated_at = now()"]
    params: list[Any] = [email, bool(verified)]
    if linkedin_url:
        set_clauses.append(f"linkedin_url = ${len(params) + 1}")
        params.append(linkedin_url)
    params.append(junction_id)
    sql = (
        f"UPDATE contact_campaigns SET {', '.join(set_clauses)} "
        f"WHERE id = ${len(params)}::uuid"
    )
    try:
        async with dbs.pool.acquire() as conn:
            await conn.execute(sql, *params)
    except Exception:
        logger.exception(
            "email_resolver: failed to update junction %s", junction_id,
        )


async def email_resolver_worker(
    config: Config,
    db_clients: DBClients,
    pattern_lookup: PatternLookup,
    smtp_verifier: Any,
) -> None:
    """Continuous worker -- resolve email for high-priority leads only."""
    del config  # accepted for signature parity with main.py registrations
    logger.info("Email resolver worker started (min_score=%d)", MIN_RESOLVE_SCORE)
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _bounded(row: asyncpg.Record) -> None:
        async with sem:
            try:
                email, verified, source, linkedin_url = await _resolve_one(
                    row, pattern_lookup, smtp_verifier, db_clients,
                )
                await _persist_resolution(
                    row, email, verified, linkedin_url, db_clients,
                )
                logger.info(
                    "email_resolver: '%s' @ %s -> email=%s verified=%s "
                    "source=%s linkedin=%s",
                    row["contact_name"],
                    row["company_name"] or "?",
                    email or "(none)",
                    verified,
                    source,
                    linkedin_url or "(none)",
                )
            except Exception:
                logger.exception(
                    "email_resolver: unhandled error for '%s'",
                    row["contact_name"],
                )

    while True:
        try:
            rows = await _fetch_resolvable_pairs(db_clients.pool)
            if rows:
                logger.info(
                    "email_resolver cycle: %d high-priority pair(s) to resolve",
                    len(rows),
                )
                await asyncio.gather(*[_bounded(r) for r in rows])
            else:
                logger.debug("email_resolver cycle: nothing to do")
        except Exception:
            logger.exception("email_resolver cycle error")
        await asyncio.sleep(_CYCLE_INTERVAL_SECONDS)
