"""Layer 5 -- Campaign scoring: structure research + score per campaign."""
from __future__ import annotations

import asyncio
import json
import logging

from src.config import Config
from src.db.campaigns import CampaignsDB
from src.db.companies import CompaniesDB
from src.db.contacts import ContactsDB
from src.db.contact_campaigns import ContactCampaignsDB
from src.gemini.client import GeminiClient
from src.scoring.prompts import STRUCTURE_AND_SCORE_PERSON

logger = logging.getLogger(__name__)
MIN_DPP_FIT_SCORE = 7
_CYCLE_INTERVAL = 240
_CONCURRENCY = 5  # max contact-campaign pairs scored in parallel
_EMPTY_COMPANY: dict = {
    "company_name": "", "industry": "Other",
    "location": "", "company_fit_score": 0,
}


def _extract_contact_fields(contact: dict) -> dict:
    """Extract denormalized contact fields from a DB row."""
    return {
        "contact_name": contact.get("name") or "",
        "job_title": contact.get("job_title") or "",
        "email": contact.get("email") or "",
        "email_verified": contact.get("email_verified") or False,
        "linkedin_url": contact.get("linkedin_url") or "",
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
    needed: set[str] = set()
    for c in contacts:
        cid = c.get("company_id")
        if cid:
            needed.add(str(cid))
    if not needed:
        return {}

    result: dict[str, dict] = {}
    for status in ("Enriched", "Partially Enriched", "Contacts Found"):
        for row in await companies_db.get_companies_by_status(status):
            pid = str(row["id"])
            if pid in needed and pid not in result:
                result[pid] = _extract_company_fields(row)
    return result


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
    try:
        result = await gemini_client.generate(
            prompt=prompt,
            user_message="Structure this research and score the contact for the campaign.",
            model=config.model_scoring, json_mode=True,
        )
        parsed = json.loads(result["text"])
        score = max(1, min(10, int(parsed.get("relevance_score", 0))))
        logger.info("Scored '%s': %d (in=%d out=%d)", contact_name, score,
                     result.get("input_tokens", 0), result.get("output_tokens", 0))
        return {
            "determined_role": str(parsed.get("determined_role", "")),
            "professional_background": str(parsed.get("professional_background", "")),
            "achievements": str(parsed.get("achievements", "")),
            "public_activity": str(parsed.get("public_activity", "")),
            "key_topics": parsed.get("key_topics", []),
            "relevance_signals": str(parsed.get("relevance_signals", "")),
            "research_quality": str(parsed.get("research_quality", "")),
            "context_summary": str(parsed.get("context_summary", "")),
            "relevance_score": score,
            "score_reasoning": str(parsed.get("score_reasoning", "")),
            "personalized_context": str(parsed.get("personalized_context", "")),
        }
    except Exception as exc:
        logger.error("Scoring failed for '%s': %s", contact_name, exc)
        return {
            "determined_role": "", "professional_background": "",
            "achievements": "", "public_activity": "",
            "key_topics": [], "relevance_signals": "",
            "research_quality": "", "context_summary": "",
            "relevance_score": 0, "score_reasoning": f"Scoring failed: {exc}",
            "personalized_context": "",
        }


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

    # Dedup: skip if already scored
    existing = await contact_campaigns_db.find_by_contact_campaign(
        contact_id, campaign_id)
    if existing:
        if (existing.get("relevance_score") or 0) > 0:
            return False

    cf = _extract_contact_fields(contact)
    campaign_name = campaign.get("name") or ""
    campaign_target = campaign.get("target_description") or ""

    # Read contact body as primary research source
    person_research = ""
    try:
        person_research = await contacts_db.get_body(contact_id)
    except Exception as exc:
        logger.warning("Cannot read contact body '%s': %s", cf["contact_name"], exc)

    # Read company body for company summary
    company_summary = ""
    if company_id:
        try:
            company_summary = await companies_db.get_body(company_id)
        except Exception as exc:
            logger.warning("Cannot read company body: %s", exc)

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

    # Junction record fields
    relevance_score = max(1, min(10, int(sr.get("relevance_score", 0))))
    score_reasoning = str(sr.get("score_reasoning", ""))
    personalized_context = str(sr.get("personalized_context", ""))
    context = str(sr.get("context_summary", ""))

    # Write junction record (update existing or create new)
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
            personalized_context=personalized_context,
            context=context,
        )
    logger.info("Scored '%s' x '%s': %d",
                cf["contact_name"], campaign_name, relevance_score)
    return True


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
