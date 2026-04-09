"""Layer 5 -- Campaign scoring worker.

Picks up contacts with status "Researched", scores each against every
active campaign via LLM, writes results to the Contact-Campaign junction.
"""
from __future__ import annotations

import asyncio
import json
import logging

from src.config import Config
from src.models.gemini import GeminiClient
from src.notion.client import NotionClient
from src.notion.databases_campaigns import CampaignsDB
from src.notion.databases_companies import CompaniesDB
from src.notion.databases_contacts import ContactsDB
from src.notion.databases_contact_campaigns import ContactCampaignsDB
from src.notion.prop_helpers import (
    extract_title, extract_rich_text, extract_email, extract_url,
    extract_checkbox, extract_number, extract_select, extract_relation_ids,
)
from src.prompts.campaign_scoring import SCORE_CONTACT_FOR_CAMPAIGN

logger = logging.getLogger(__name__)
_CYCLE_INTERVAL = 240
_CONCURRENCY = 5  # max contact-campaign pairs scored in parallel
_EMPTY_COMPANY: dict = {
    "company_name": "", "industry": "Other",
    "location": "", "company_fit_score": 0,
}


def _blocks_to_text(blocks: list[dict]) -> str:
    """Extract plain text from Notion block objects."""
    parts = []
    for block in blocks:
        btype = block.get("type", "")
        rich_texts = block.get(btype, {}).get("rich_text", [])
        text = "".join(rt.get("plain_text", "") for rt in rich_texts)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _extract_contact_fields(contact: dict) -> dict:
    """Extract denormalized contact fields from a contact page."""
    return {
        "contact_name": extract_title(contact, "Name"),
        "job_title": extract_rich_text(contact, "Job Title"),
        "email": extract_email(contact, "Email"),
        "email_verified": extract_checkbox(contact, "Email Verified"),
        "linkedin_url": extract_url(contact, "LinkedIn URL"),
    }


def _extract_company_fields(company: dict) -> dict:
    """Extract denormalized company fields from a company page."""
    return {
        "company_name": extract_title(company, "Name"),
        "industry": extract_select(company, "Industry") or "Other",
        "location": extract_rich_text(company, "Location"),
        "company_fit_score": extract_number(company, "DPP Fit Score") or 0,
    }


async def _fetch_company_map(
    contacts: list[dict], companies_db: CompaniesDB
) -> dict[str, dict]:
    """Pre-fetch company data for all contacts, keyed by company page ID."""
    needed: set[str] = set()
    for c in contacts:
        cids = extract_relation_ids(c, "Company")
        if cids:
            needed.add(cids[0])
    if not needed:
        return {}
    result: dict[str, dict] = {}
    for status in ("Enriched", "Partially Enriched", "Contacts Found"):
        for page in await companies_db.get_companies_by_status(status):
            pid = page["id"]
            if pid in needed and pid not in result:
                result[pid] = _extract_company_fields(page)
    return result


async def _score_with_llm(
    gemini_client: GeminiClient, config: Config,
    campaign_target: str, contact_name: str, job_title: str,
    company_name: str, person_research: str, company_summary: str,
) -> dict:
    """Call Gemini to score a contact against a campaign target."""
    prompt = (
        SCORE_CONTACT_FOR_CAMPAIGN
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
            user_message="Score this contact for the campaign.",
            model=config.model_scoring, json_mode=True,
        )
        parsed = json.loads(result["text"])
        score = max(1, min(10, int(parsed.get("relevance_score", 0))))
        logger.info("Scored '%s': %d (in=%d out=%d)", contact_name, score,
                     result.get("input_tokens", 0), result.get("output_tokens", 0))
        return {
            "relevance_score": score,
            "score_reasoning": str(parsed.get("score_reasoning", "")),
            "personalized_context": str(parsed.get("personalized_context", "")),
        }
    except Exception as exc:
        logger.error("Scoring failed for '%s': %s", contact_name, exc)
        return {"relevance_score": 0, "score_reasoning": f"Scoring failed: {exc}",
                "personalized_context": ""}


async def _process_pair(
    contact: dict, campaign: dict, config: Config,
    gemini_client: GeminiClient, notion_client: NotionClient,
    contact_campaigns_db: ContactCampaignsDB,
    company_fields: dict, company_id: str,
) -> bool:
    """Score one contact against one campaign. Returns True if scored."""
    contact_id, campaign_id = contact["id"], campaign["id"]

    # Dedup: skip if already scored
    existing = await contact_campaigns_db.find_by_contact_campaign(
        contact_id, campaign_id)
    if existing:
        if (extract_number(existing, "Relevance Score") or 0) > 0:
            return False

    cf = _extract_contact_fields(contact)
    campaign_name = extract_title(campaign, "Name")
    campaign_target = extract_rich_text(campaign, "Target Description")

    # Read Context property first; fall back to page body if empty
    person_research = extract_rich_text(contact, "Context")
    if not person_research:
        try:
            person_research = _blocks_to_text(
                await notion_client.get_page_body(contact_id))
        except Exception as exc:
            logger.warning("Cannot read contact body '%s': %s", cf["contact_name"], exc)

    company_summary = ""
    if company_id:
        try:
            company_summary = _blocks_to_text(
                await notion_client.get_page_body(company_id))
        except Exception as exc:
            logger.warning("Cannot read company body: %s", exc)

    sr = await _score_with_llm(
        gemini_client, config, campaign_target, cf["contact_name"],
        cf["job_title"], company_fields.get("company_name", ""),
        person_research, company_summary,
    )

    # Write junction record (update existing or create new)
    if existing:
        await contact_campaigns_db.update_score(
            existing["id"], sr["relevance_score"],
            sr["score_reasoning"], sr["personalized_context"])
    else:
        contact_context = extract_rich_text(contact, "Context")
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
            relevance_score=sr["relevance_score"],
            score_reasoning=sr["score_reasoning"],
            personalized_context=sr["personalized_context"],
            context=contact_context,
        )
    logger.info("Scored '%s' x '%s': %d",
                cf["contact_name"], campaign_name, sr["relevance_score"])
    return True


async def campaign_scoring_worker(
    config: Config, gemini_client: GeminiClient, notion_client: NotionClient,
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

            contacts = await notion_client.query_database(
                contacts_db.db_id,
                filter_obj={"property": "Status", "select": {"equals": "Researched"}},
            )
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

            async def _bounded(contact: dict, campaign: dict,
                               cfields: dict, cid: str) -> None:
                nonlocal scored
                async with sem:
                    try:
                        if await _process_pair(
                            contact, campaign, config, gemini_client,
                            notion_client, contact_campaigns_db, cfields, cid,
                        ):
                            async with scored_lock:
                                scored += 1
                    except Exception as exc:
                        logger.error("Error scoring '%s' x '%s': %s",
                                     extract_title(contact, "Name"),
                                     extract_title(campaign, "Name"), exc)

            tasks = []
            for contact in contacts:
                cids = extract_relation_ids(contact, "Company")
                cid = cids[0] if cids else ""
                cfields = company_map.get(cid, _EMPTY_COMPANY)
                for campaign in campaigns:
                    tasks.append(_bounded(contact, campaign, cfields, cid))
            await asyncio.gather(*tasks)

            if scored:
                logger.info("Campaign scoring cycle: %d pairs scored", scored)
        except Exception as exc:
            logger.error("Campaign scoring cycle error: %s", exc)
        await asyncio.sleep(_CYCLE_INTERVAL)
