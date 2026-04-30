"""Person research worker -- single grounded structured call per contact.

Per F6/F16. Picks up Enriched contacts, runs one Gemini grounded call
per contact using the Strict-Prompt-Template ``RESEARCH_PERSON_STRUCTURED``
prompt, persists ``research_text`` to ``contacts.body`` via ``set_body``,
and flips the contact to ``Researched`` so the scoring worker (task 013)
picks it up.

Two pre-call gates:
    1. ``is_relevant_title(title)`` -- filters junior / non-target roles.
    2. company ``dpp_fit_score >= 7`` -- below-threshold companies skip.
Both gates still mark the contact ``Researched`` so the pipeline does
not stall.

On tolerant-JSON parse failure (after the single retry) the worker also
marks the contact ``Researched`` -- the body simply stays empty. The
scoring worker tolerates empty bodies and falls back to company context.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse
from uuid import UUID

from src.db.companies import CompaniesDB
from src.db.contacts import ContactsDB
from src.gemini.client import GeminiClient
from src.people.title_filter import is_relevant_title
from src.person_research.prompts import RESEARCH_PERSON_STRUCTURED
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)

MIN_DPP_FIT_SCORE = 7
_CYCLE_INTERVAL = 300  # 5 min -- matched to people-worker pace; the
# combined upstream cadence is now (10/4/5/5/6) min so leads reach
# the email_resolver at a rate the Prospeo pool can actually keep up
# with sustainably.
_CONCURRENCY = 5  # max contacts researched in parallel per cycle

_SENTINEL_STRINGS = {"unknown", "n/a", "none", "no data found"}


# Pure helpers ---------------------------------------------------------


def _extract_domain(website_url: str) -> str:
    """Return the bare hostname for ``website_url`` (no scheme, no ``www.``)."""
    if not website_url:
        return ""
    candidate = website_url.strip()
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"
    try:
        host = urlparse(candidate).hostname or ""
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _render_prompt(
    *, name: str, title: str, company_name: str, domain: str,
) -> str:
    """Inline-substitute the four named placeholders into the prompt."""
    return (
        RESEARCH_PERSON_STRUCTURED
        .replace("{contact_name}", name)
        .replace("{contact_title}", title)
        .replace("{company_name}", company_name)
        .replace("{domain}", domain)
    )


def _coerce_research_text(value: object) -> str:
    """Return a stripped ``research_text`` string, dropping sentinels."""
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if cleaned.lower() in _SENTINEL_STRINGS:
        return ""
    return cleaned


# DB lookup ------------------------------------------------------------


async def _fetch_company_info(
    companies_db: CompaniesDB, company_id: str,
) -> tuple[str, str, float | None]:
    """Return ``(name, domain, dpp_fit_score)`` or ``("", "", None)``.

    Any failure (missing ID, bad UUID, no row, asyncpg error) collapses
    to the empty triple so callers can short-circuit cleanly.
    """
    if not company_id:
        return "", "", None
    try:
        company_uuid = UUID(company_id)
    except (TypeError, ValueError):
        return "", "", None
    try:
        row = await companies_db._pool.fetchrow(
            "SELECT name, website, dpp_fit_score "
            "FROM companies WHERE id = $1",
            company_uuid,
        )
    except Exception:
        logger.exception(
            "Person research: company lookup failed for id=%s", company_id,
        )
        return "", "", None
    if row is None:
        return "", "", None
    return (
        row["name"] or "",
        _extract_domain(row["website"] or ""),
        row["dpp_fit_score"],
    )


# Per-contact research -------------------------------------------------


async def _research_contact(
    contact: dict,
    gemini_client: GeminiClient,
    contacts_db: ContactsDB,
    companies_db: CompaniesDB,
) -> None:
    """Run one grounded structured call and persist the result."""
    contact_id = str(contact["id"])
    name = (contact.get("name") or "").strip()
    title = (contact.get("job_title") or "").strip()
    company_id = contact.get("company_id")

    # Gate 1: title relevance.
    if not is_relevant_title(title):
        logger.info(
            "Person research: skipping '%s' -- title '%s' not relevant",
            name or "?", title or "(empty)",
        )
        await contacts_db.update_contact(contact_id, status="Researched")
        return

    company_name, domain, dpp_score = await _fetch_company_info(
        companies_db, str(company_id) if company_id else "",
    )

    # Gate 2: DPP fit score threshold.
    if (dpp_score or 0) < MIN_DPP_FIT_SCORE:
        logger.info(
            "Person research: skipping '%s' -- '%s' DPP=%s < %d",
            name or "?", company_name or "?", dpp_score, MIN_DPP_FIT_SCORE,
        )
        await contacts_db.update_contact(contact_id, status="Researched")
        return

    rendered = _render_prompt(
        name=name, title=title, company_name=company_name, domain=domain,
    )

    async def _call(user_message: str) -> dict:
        return await gemini_client.generate(
            prompt=rendered,
            user_message=user_message,
            # No grounding for F16 compatibility (Gemini 2.5 rejects
            # grounding+json_mode). Person research prompt already pins
            # contact_name + title + company_name; the model recalls
            # publicly-known activity from training data. Loses recency
            # on news/launches; gain reliability across the tier ladder.
            grounding=False,
            json_mode=True,
            max_retries=30,
        )

    base_user_message = (
        f"Research {name} ({title}) at "
        f"{company_name or domain or 'the target company'}."
    )

    logger.info(
        "Person research: Gemini call for '%s' (%s) at '%s'",
        name, title, company_name,
    )
    result = await retry_on_malformed_json(_call, base_user_message)

    if result is None:
        logger.warning(
            "Person research: parse failed for '%s'; marking Researched "
            "with empty body",
            name,
        )
        await contacts_db.update_contact(contact_id, status="Researched")
        return

    parsed, raw = result
    if not isinstance(parsed, dict):
        logger.warning(
            "Person research: non-dict payload for '%s': %r", name, parsed,
        )
        await contacts_db.update_contact(contact_id, status="Researched")
        return

    research_text = _coerce_research_text(parsed.get("research_text"))
    await contacts_db.set_body(contact_id, research_text)
    await contacts_db.update_contact(contact_id, status="Researched")
    logger.info(
        "Person research: '%s' done (chars=%d, in=%d out=%d, served=%s)",
        name,
        len(research_text),
        raw.get("input_tokens", 0),
        raw.get("output_tokens", 0),
        raw.get("served_model", ""),
    )


# Worker entrypoint ----------------------------------------------------


async def _bounded(
    contact: dict,
    sem: asyncio.Semaphore,
    gemini_client: GeminiClient,
    contacts_db: ContactsDB,
    companies_db: CompaniesDB,
) -> None:
    """Run ``_research_contact`` under the concurrency semaphore.

    Errors are logged but never propagate so one bad contact does not
    abort the cycle's ``asyncio.gather``. On exception we ALSO advance
    the contact's status to ``Researched`` (with empty body) so it
    doesn't get retried forever in the same exhausted state -- the
    pipeline can move forward with whatever data is present, and a
    future re-run of the campaign can re-research if needed.
    """
    async with sem:
        try:
            await _research_contact(
                contact, gemini_client, contacts_db, companies_db,
            )
        except Exception:
            name = contact.get("name", "?")
            logger.exception(
                "Person research: unhandled error for '%s'; marking "
                "Researched with empty body to avoid infinite retry",
                name,
            )
            try:
                contact_id = str(contact.get("id"))
                if contact_id:
                    await contacts_db.update_contact(
                        contact_id, status="Researched",
                    )
            except Exception:
                logger.exception(
                    "Person research: also failed to mark '%s' Researched",
                    name,
                )


async def person_research_worker(
    config,  # accepted for signature parity with main.py
    gemini_client: GeminiClient,
    contacts_db: ContactsDB,
    companies_db: CompaniesDB,
) -> None:
    """Continuous worker -- one grounded structured call per Enriched contact.

    Signature matches the legacy worker so ``src/main.py`` schedules it
    unchanged. ``config`` is no longer read here -- per F16 the api_keys
    pool picks the served model and the prompt defends against tier
    downshift.
    """
    del config  # signature-only; unused since task 003.
    logger.info("Person research worker started")
    sem = asyncio.Semaphore(_CONCURRENCY)
    while True:
        try:
            contacts = await contacts_db.get_contacts_by_status("Enriched")
            logger.info(
                "Person research: %d enriched contact(s) this cycle",
                len(contacts),
            )
            if contacts:
                await asyncio.gather(*[
                    _bounded(c, sem, gemini_client, contacts_db, companies_db)
                    for c in contacts
                ])
        except Exception:
            logger.exception("Person research worker cycle error")
        await asyncio.sleep(_CYCLE_INTERVAL)
