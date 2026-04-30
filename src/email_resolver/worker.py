"""Email resolver worker -- runs only on high-priority leads.

Polls contact_campaigns where relevance_score >= MIN_RESOLVE_SCORE and
the contact has no email yet, resolves the email + LinkedIn URL +
(optionally) phone, persists back to contacts and contact_campaigns
plus the email_verified flag.

Provider waterfall (only two layers now -- Hunter + pattern were
removed because their hit rate on niche EU brands was effectively zero
and they polluted the persisted email column with low-quality guesses):
  1. Prospeo enrich-person -- multi-key pool, 1 credit per email+
     LinkedIn lookup, 10 credits if mobile is requested. Primary.
  2. Gemini grounded fallback -- runs only on Prospeo NO_MATCH.
     Single grounded Google Search call mines team pages, conference
     bios, etc. for LinkedIn URL + likely email. Email goes through
     MyEmailVerifier downstream so we never persist Gemini's guess
     without proof.

Deferred to scoring time so we don't spend any provider quota on
contacts that ultimately score too low to email.
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
from src.people.gemini_grounded_finder import (
    GeminiGroundedFinder, GeminiFinderResult,
)
from src.people.helpers import extract_domain, split_name
from src.people.prospeo_finder import ProspeoFinder, ProspeoResult

logger = logging.getLogger(__name__)

MIN_RESOLVE_SCORE = 7  # mirrors MIN_DPP_FIT_SCORE used elsewhere
_CYCLE_INTERVAL_SECONDS = 240  # 4 min between cycles (was 3) -- gentler
# pace prevents bursting through the Prospeo monthly budget when a
# scoring batch suddenly drops 20+ high-priority leads at once.
_CONCURRENCY = 1  # serial resolution. The Gemini-grounded fallback
# is slow (~30-60s per call) and the private Tier-1 backup has a 2s
# per-call throttle; running two contacts in parallel doubled the
# throttle wait and stacked into the request timeout. Serial keeps
# the private key serving one finder request at a time, max one
# Prospeo call at a time -- predictable cadence.
_PER_CALL_DELAY_SECONDS = 0.6  # small jitter between consecutive
# resolutions in the same cycle so a burst of 50 leads stretches
# across ~30s rather than hammering Prospeo in 2-3s.


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
    # re-fetched every cycle, burning credits indefinitely.
    #
    # Cooldown clause -- skip rows touched in the last 6 hours so a
    # contact Prospeo can't match doesn't get re-tried on every 3-min
    # cycle, stealing concurrency slots from new high-priority leads.
    # Distinguish "freshly scored, never tried" from "tried, missed":
    # scoring inserts with updated_at = created_at; the resolver bumps
    # updated_at on every persist, so a 1s tolerance separates the two.
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
            co.website      AS company_website
        FROM contact_campaigns cc
        JOIN contacts c   ON cc.contact_id = c.id
        LEFT JOIN companies co ON cc.company_id = co.id
        WHERE cc.relevance_score >= $1
          AND (c.email IS NULL OR c.email = '')
          AND (
                cc.updated_at IS NULL
             OR cc.updated_at <= cc.created_at + interval '1 second'
             OR cc.updated_at < now() - interval '6 hours'
          )
        ORDER BY cc.relevance_score DESC, cc.created_at ASC
        LIMIT 50
    """
    async with pool.acquire() as conn:
        return await conn.fetch(sql, MIN_RESOLVE_SCORE)


@dataclass
class ResolverResult:
    """Outcome of one resolve cycle for a contact -- carries every
    field the persistence step writes to ``contacts`` and
    ``contact_campaigns``. Empty strings/False are the "no data" sentinels.
    """

    email: str = ""
    email_verified: bool = False
    linkedin_url: str = ""
    phone: str = ""
    source: str = "none"


async def _resolve_one(
    row: asyncpg.Record,
    prospeo_finder: ProspeoFinder | None,
    gemini_finder: GeminiGroundedFinder | None,
    smtp_verifier: Any,
    dbs: DBClients,
    *,
    enrich_mobile: bool,
) -> ResolverResult:
    """Resolve one (contact, campaign) pair through the provider waterfall.

    1. Prospeo enrich-person (primary) -- email + LinkedIn URL natively;
       phone too if ``enrich_mobile`` is True (10x credit cost).
    2. Gemini grounded fallback -- runs only on Prospeo NO_MATCH.
       Single grounded Google Search call mines team pages, conference
       bios, etc. for LinkedIn URL + likely email. Email goes through
       MyEmailVerifier downstream so we never persist Gemini's guess
       without proof.

    A partial Prospeo hit (linkedin only, no email) keeps its
    linkedin_url while the Gemini fallback fills in the missing email.
    """
    contact_name = row["contact_name"] or ""
    website = row["company_website"] or ""
    domain = extract_domain(website)

    if not contact_name or not domain:
        return ResolverResult()

    first, last = split_name(contact_name)
    result = ResolverResult()
    prospeo_missed = False  # set True when Prospeo returned NO_MATCH

    # 1. Prospeo (primary). Provides email + LinkedIn URL + phone in
    # one call. Populates the result; we keep going only if email is
    # missing so Gemini / Hunter / pattern can fill that gap.
    if prospeo_finder is not None and prospeo_finder.enabled:
        prospeo_hit: ProspeoResult | None = await prospeo_finder.find(
            first, last, domain, enrich_mobile=enrich_mobile,
        )
        if prospeo_hit is None:
            # NO_MATCH / INVALID_DATAPOINTS / pool exhausted -- mark
            # so the Gemini fallback below can fire on the right rows.
            prospeo_missed = True
        else:
            if prospeo_hit.linkedin_url:
                result.linkedin_url = prospeo_hit.linkedin_url
            if prospeo_hit.phone:
                result.phone = prospeo_hit.phone
            if prospeo_hit.email:
                # Prospeo flags VERIFIED when its own MX-level checks
                # pass. We still run MyEmailVerifier downstream in case
                # the address has gone stale since Prospeo crawled it.
                if prospeo_hit.email_verified:
                    result.email = prospeo_hit.email
                    result.email_verified = True
                    result.source = "prospeo"
                else:
                    verified = await _verify(prospeo_hit.email, smtp_verifier)
                    if verified:
                        result.email = prospeo_hit.email
                        result.email_verified = True
                        result.source = "prospeo+verifier"
                    else:
                        logger.info(
                            "email_resolver: Prospeo email %s did not verify;"
                            " falling through",
                            prospeo_hit.email,
                        )

    if result.email:
        return result

    # 2. Gemini grounded fallback. Runs only when Prospeo missed
    # (NO_MATCH / no data) -- single grounded Google Search call to
    # find LinkedIn URL + likely email from public sources Prospeo
    # doesn't index. Skipped if we already tried this contact within
    # the cooldown window so we don't burn paid grounded-search quota
    # on the same dead-end contact every cycle.
    if (
        prospeo_missed
        and gemini_finder is not None
        and gemini_finder.enabled
    ):
        contact_id = (
            str(row["contact_id"]) if row["contact_id"] else None
        )
        already_tried = await gemini_finder.already_tried_recently(contact_id)
        if not already_tried:
            company_name = row["company_name"] or ""
            job_title = row["job_title"] or ""
            # Pull the contact's research body for richer context. If
            # the read fails, fall through with empty context -- never
            # block the resolver on a body fetch.
            ctx = ""
            try:
                ctx = await dbs.contacts.get_body(contact_id) if contact_id else ""
            except Exception:
                logger.warning(
                    "email_resolver: failed to fetch context body for %s",
                    contact_id, exc_info=True,
                )
            gemini_hit: GeminiFinderResult | None = await gemini_finder.find(
                contact_id=contact_id,
                contact_name=contact_name,
                job_title=job_title,
                company_name=company_name,
                company_website=website,
                domain=domain,
                context=ctx,
            )
            if gemini_hit is not None:
                if gemini_hit.linkedin_url and not result.linkedin_url:
                    result.linkedin_url = gemini_hit.linkedin_url
                if gemini_hit.email:
                    verified = await _verify(gemini_hit.email, smtp_verifier)
                    if verified:
                        result.email = gemini_hit.email
                        result.email_verified = True
                        result.source = "gemini_grounded"
                        return result
                    logger.info(
                        "email_resolver: Gemini email %s did not verify; "
                        "leaving contact unresolved",
                        gemini_hit.email,
                    )

    return result


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
    result: ResolverResult,
    dbs: DBClients,
) -> None:
    """Update contacts + contact_campaigns with the resolved fields.

    Each non-empty field is written to BOTH tables so the leads_full
    view (which reads ``cc.linkedin_url`` / ``cc.phone``) stays in
    sync with the canonical contacts table. Empty strings never
    overwrite a populated column -- a field that was already set by
    a previous resolver pass survives even if this pass missed.
    """
    contact_id = str(row["contact_id"])
    junction_id = str(row["junction_id"])

    has_any = bool(
        result.email or result.linkedin_url or result.phone,
    )
    if has_any:
        contact_fields: dict[str, Any] = {}
        if result.email:
            contact_fields["email"] = result.email
            contact_fields["email_verified"] = result.email_verified
        if result.linkedin_url:
            contact_fields["linkedin_url"] = result.linkedin_url
        if result.phone:
            contact_fields["phone"] = result.phone
        try:
            await dbs.contacts.update_contact(contact_id, **contact_fields)
        except Exception:
            logger.exception(
                "email_resolver: failed to update contact %s", contact_id,
            )

    # Build the junction UPDATE dynamically so empty values don't blank
    # populated columns. ``email`` + ``email_verified`` are always
    # written because the email lookup is the trigger for this row
    # leaving the resolvable-pairs query (callers expect the email
    # column to reflect the latest attempt, even on miss).
    set_clauses = ["email = $1", "email_verified = $2", "updated_at = now()"]
    params: list[Any] = [result.email, bool(result.email_verified)]
    if result.linkedin_url:
        set_clauses.append(f"linkedin_url = ${len(params) + 1}")
        params.append(result.linkedin_url)
    if result.phone:
        set_clauses.append(f"phone = ${len(params) + 1}")
        params.append(result.phone)
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
    smtp_verifier: Any,
    prospeo_finder: ProspeoFinder | None = None,
    gemini_finder: GeminiGroundedFinder | None = None,
) -> None:
    """Continuous worker -- resolve email for high-priority leads only.

    ``prospeo_finder`` is optional so existing deployments that don't
    set ``PROSPEO_API_KEYS`` continue working with Hunter as the only
    provider; when configured, Prospeo is the primary and Hunter the
    fallback. ``gemini_finder`` is the grounded-search fallback that
    runs on Prospeo NO_MATCHes; pass None to disable.
    """
    enrich_mobile = bool(getattr(config, "prospeo_enrich_mobile", False))
    logger.info(
        "Email resolver worker started (min_score=%d prospeo=%s "
        "gemini=%s enrich_mobile=%s)",
        MIN_RESOLVE_SCORE,
        "enabled" if (prospeo_finder and prospeo_finder.enabled) else "disabled",
        "enabled" if (gemini_finder and gemini_finder.enabled) else "disabled",
        enrich_mobile,
    )
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _bounded(row: asyncpg.Record) -> None:
        async with sem:
            try:
                result = await _resolve_one(
                    row, prospeo_finder, gemini_finder,
                    smtp_verifier, db_clients,
                    enrich_mobile=enrich_mobile,
                )
                await _persist_resolution(row, result, db_clients)
                # Spread credit burn across the cycle: a small jitter
                # after each call means a 50-row batch stretches across
                # ~30s rather than spiking Prospeo's rate-limiter in
                # 2-3s. The semaphore continues holding so this delay
                # contributes to overall pacing, not just per-task.
                if _PER_CALL_DELAY_SECONDS > 0:
                    await asyncio.sleep(_PER_CALL_DELAY_SECONDS)
                logger.info(
                    "email_resolver: '%s' @ %s -> email=%s verified=%s "
                    "source=%s linkedin=%s phone=%s",
                    row["contact_name"],
                    row["company_name"] or "?",
                    result.email or "(none)",
                    result.email_verified,
                    result.source,
                    result.linkedin_url or "(none)",
                    result.phone or "(none)",
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
