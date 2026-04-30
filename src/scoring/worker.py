"""Layer 5 -- Campaign scoring: structure research + score per campaign.

Per task 013: the prompt follows the Strict Prompt Template (F16) and
JSON parsing goes through ``retry_on_malformed_json`` (tolerant
extractor + one retry). Worker logic is preserved -- ``MIN_DPP_FIT_SCORE``
gate, ``_process_pair`` flow, denormalized contact + junction writes,
score clamping, and concurrency are unchanged.
"""

from __future__ import annotations

import asyncio
import logging

from src.config import Config
from src.db.campaigns import CampaignsDB
from src.db.companies import CompaniesDB
from src.db.contacts import ContactsDB
from src.db.contact_campaigns import ContactCampaignsDB
from src.gemini.client import GeminiClient
from src.scoring.prompts import STRUCTURE_AND_SCORE_PERSON
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)
MIN_DPP_FIT_SCORE = 7
_CYCLE_INTERVAL = 360  # 6 min -- last upstream stage before the
# email_resolver. Bumped from 4 min so the queue of high-priority
# leads grows at a pace Prospeo's 1-credit-per-call rate can absorb.
_CONCURRENCY = 5  # max contact-campaign pairs scored in parallel
_EMPTY_COMPANY: dict = {
    "company_name": "", "industry": "Other",
    "location": "", "company_fit_score": 0,
}

_STR_FIELDS = (
    "determined_role", "professional_background", "achievements",
    "public_activity", "relevance_signals", "research_quality",
    "context_summary", "personalized_context",
)


def _build_score(parsed: dict | None, score: int, reason: str = "") -> dict:
    """Project a parsed JSON dict onto the worker's flat score record."""
    p = parsed or {}
    out = {k: str(p.get(k, "")) for k in _STR_FIELDS}
    out["key_topics"] = p.get("key_topics", []) if parsed else []
    out["relevance_score"] = score
    out["score_reasoning"] = reason or str(p.get("score_reasoning", ""))
    return out


def _extract_contact_fields(contact: dict) -> dict:
    """Extract denormalized contact fields from a DB row."""
    return {
        "contact_name": contact.get("name") or "",
        "job_title": contact.get("job_title") or "",
        "email": contact.get("email") or "",
        "email_verified": contact.get("email_verified") or False,
        # Force empty: the model cannot reliably know LinkedIn slug URLs
        # (they redirect to dead pages). Even if a stray non-empty value
        # leaked into contacts.linkedin_url, do NOT propagate it into the
        # contact_campaigns junction -- that view powers the leads
        # dashboard's clickable link.
        "linkedin_url": "",
    }


def _extract_company_fields(company: dict) -> dict:
    """Extract denormalized company fields from a DB row."""
    return {
        "company_name": company.get("name") or "",
        "industry": company.get("industry") or "Other",
        "location": company.get("location") or "",
        "company_fit_score": company.get("dpp_fit_score") or 0,
    }


async def _fetch_company_map(
    contacts: list[dict], companies_db: CompaniesDB,
) -> dict[str, dict]:
    """Pre-fetch company data for all contacts, keyed by company UUID string."""
    needed: set[str] = {str(c["company_id"]) for c in contacts if c.get("company_id")}
    if not needed:
        return {}
    result: dict[str, dict] = {}
    for status in ("Enriched", "Partially Enriched", "Contacts Found"):
        for row in await companies_db.get_companies_by_status(status):
            pid = str(row["id"])
            if pid in needed and pid not in result:
                result[pid] = _extract_company_fields(row)
    return result


def _coerce_score(parsed: dict, contact_name: str) -> int:
    """Clamp the model's relevance_score to 1..10; default 0 on bad input."""
    try:
        return max(1, min(10, int(parsed.get("relevance_score", 0))))
    except (TypeError, ValueError) as exc:
        logger.warning("Scoring: bad relevance_score for '%s': %s",
                       contact_name, exc)
        return 0


async def _score_with_llm(
    gemini_client: GeminiClient, config: Config,
    campaign_target: str, contact_name: str, job_title: str,
    company_name: str, person_research: str, company_summary: str,
) -> dict:
    """Call Gemini to structure research and score a contact for a campaign."""
    prompt = (
        STRUCTURE_AND_SCORE_PERSON
        .replace("{campaign_target}", campaign_target or "(no campaign target provided)")
        .replace("{contact_name}", contact_name or "Unknown")
        .replace("{contact_title}", job_title or "Unknown")
        .replace("{company_name}", company_name or "Unknown")
        .replace("{person_research}", person_research or "(no person research available)")
        .replace("{company_summary}", company_summary or "(no company enrichment available)")
    )

    async def _call(user_message: str) -> dict:
        return await gemini_client.generate(
            prompt=prompt, user_message=user_message,
            model=config.model_scoring, json_mode=True,
            max_retries=30,
        )

    base_msg = "Structure this research and score the contact for the campaign."
    try:
        result = await retry_on_malformed_json(_call, base_msg)
    except Exception as exc:
        return _fail(contact_name, f"Scoring failed: {exc}")
    if result is None:
        return _fail(contact_name, "Scoring failed: malformed JSON after retry")
    parsed, raw = result
    if not isinstance(parsed, dict):
        return _fail(contact_name,
                     f"Scoring failed: parsed value type={type(parsed).__name__}")

    score = _coerce_score(parsed, contact_name)
    logger.info("Scored '%s': %d (in=%d out=%d)", contact_name, score,
                raw.get("input_tokens", 0), raw.get("output_tokens", 0))
    return _build_score(parsed, score)


def _fail(contact_name: str, reason: str) -> dict:
    """Log a scoring failure and return the empty score record."""
    logger.error("Scoring '%s': %s", contact_name, reason)
    return _build_score(None, 0, reason)


async def _process_pair(
    contact: dict, campaign: dict, config: Config,
    gemini_client: GeminiClient,
    contacts_db: ContactsDB, contact_campaigns_db: ContactCampaignsDB,
    companies_db: CompaniesDB,
    company_fields: dict, company_id: str,
    updated_contacts: set[str],
) -> bool:
    """Score one contact against one campaign. Returns True if scored."""
    contact_id = str(contact["id"])
    campaign_id = str(campaign["id"])

    # Dedup: skip if already scored, BUT retry if the existing score
    # came from a Gemini-call failure (score=1 fallback with reasoning
    # starting "Scoring failed:"). Otherwise transient pool exhaustion
    # would freeze the contact at score=1 permanently.
    existing = await contact_campaigns_db.find_by_contact_campaign(
        contact_id, campaign_id)
    if existing and (existing.get("relevance_score") or 0) > 0:
        prior_reason = (existing.get("score_reasoning") or "")
        if prior_reason.startswith("Scoring failed:"):
            logger.info(
                "Re-scoring '%s' x '%s' (prior was a failure fallback)",
                contact.get("name", "?"), campaign.get("name", "?"),
            )
        else:
            return False

    cf = _extract_contact_fields(contact)
    campaign_name = campaign.get("name") or ""
    campaign_target = campaign.get("target_description") or ""

    person_research = await _safe_body(contacts_db, contact_id,
                                       cf["contact_name"], "contact")
    company_summary = await _safe_body(
        companies_db, company_id, "", "company") if company_id else ""

    sr = await _score_with_llm(
        gemini_client, config, campaign_target, cf["contact_name"],
        cf["job_title"], company_fields.get("company_name", ""),
        person_research, company_summary,
    )

    # Update contact-level fields (first campaign to process wins)
    if contact_id not in updated_contacts:
        update_kw: dict = {}
        determined_role = sr.get("determined_role", "")
        if determined_role and determined_role != cf["job_title"]:
            update_kw["job_title"] = determined_role
        context_summary = sr.get("context_summary", "")
        if context_summary:
            update_kw["context"] = context_summary
        if update_kw:
            await contacts_db.update_contact(contact_id, **update_kw)
        updated_contacts.add(contact_id)

    relevance_score = max(1, min(10, int(sr.get("relevance_score", 0))))
    score_reasoning = str(sr.get("score_reasoning", ""))
    personalized_context = str(sr.get("personalized_context", ""))
    context = str(sr.get("context_summary", ""))

    if existing:
        await contact_campaigns_db.update_score(
            str(existing["id"]), relevance_score,
            score_reasoning, personalized_context)
    else:
        await contact_campaigns_db.create_entry(
            contact_id=contact_id, campaign_id=campaign_id,
            company_id=company_id, contact_name=cf["contact_name"],
            campaign_name=campaign_name, job_title=cf["job_title"],
            company_name=company_fields.get("company_name", ""),
            email_addr=cf["email"], email_verified=cf["email_verified"],
            linkedin_url=cf["linkedin_url"],
            industry=company_fields.get("industry", "Other"),
            location=company_fields.get("location", ""),
            company_fit_score=company_fields.get("company_fit_score", 0),
            relevance_score=relevance_score,
            score_reasoning=score_reasoning,
            personalized_context=personalized_context, context=context,
        )
    logger.info("Scored '%s' x '%s': %d",
                cf["contact_name"], campaign_name, relevance_score)
    return True


async def _safe_body(db, row_id: str, label: str, kind: str) -> str:
    """Fetch ``db.get_body(row_id)`` returning ``""`` on any error."""
    try:
        return await db.get_body(row_id)
    except Exception as exc:
        logger.warning("Cannot read %s body '%s': %s", kind, label, exc)
        return ""


async def campaign_scoring_worker(
    config: Config, gemini_client: GeminiClient,
    contacts_db: ContactsDB, companies_db: CompaniesDB,
    campaigns_db: CampaignsDB, contact_campaigns_db: ContactCampaignsDB,
) -> None:
    """Continuous worker: scores researched contacts against active campaigns."""
    logger.info("Campaign scoring worker started")
    while True:
        try:
            campaigns = await campaigns_db.get_processable_campaigns()
            if not campaigns:
                logger.debug("Campaign scoring: no processable campaigns")
                await asyncio.sleep(_CYCLE_INTERVAL)
                continue

            contacts = await contacts_db.get_contacts_by_status("Researched")
            if not contacts:
                logger.debug("Campaign scoring: no researched contacts")
                await asyncio.sleep(_CYCLE_INTERVAL)
                continue

            logger.info("Campaign scoring: %d contacts x %d campaigns",
                        len(contacts), len(campaigns))
            company_map = await _fetch_company_map(contacts, companies_db)
            scored = 0
            scored_lock = asyncio.Lock()
            sem = asyncio.Semaphore(_CONCURRENCY)
            updated_contacts: set[str] = set()

            async def _bounded(contact: dict, campaign: dict,
                               cfields: dict, cid: str) -> None:
                nonlocal scored
                async with sem:
                    try:
                        if await _process_pair(
                            contact, campaign, config, gemini_client,
                            contacts_db, contact_campaigns_db,
                            companies_db, cfields, cid,
                            updated_contacts,
                        ):
                            async with scored_lock:
                                scored += 1
                    except Exception as exc:
                        logger.error("Error scoring '%s' x '%s': %s",
                                     contact.get("name", "?"),
                                     campaign.get("name", "?"), exc)

            tasks = []
            for contact in contacts:
                cid = str(contact["company_id"]) if contact.get("company_id") else ""
                cfields = company_map.get(cid, _EMPTY_COMPANY)

                # Gate: skip contacts whose company is below DPP fit threshold
                company_score = cfields.get("company_fit_score", 0) or 0
                if company_score < MIN_DPP_FIT_SCORE:
                    logger.info(
                        "Campaign scoring: skipping '%s' (company DPP=%s, min=%d)",
                        contact.get("name", "?"),
                        company_score, MIN_DPP_FIT_SCORE,
                    )
                    continue

                for campaign in campaigns:
                    tasks.append(_bounded(contact, campaign, cfields, cid))
            await asyncio.gather(*tasks)

            if scored:
                logger.info("Campaign scoring cycle: %d pairs scored", scored)
        except Exception as exc:
            logger.error("Campaign scoring cycle error: %s", exc)
        await asyncio.sleep(_CYCLE_INTERVAL)
