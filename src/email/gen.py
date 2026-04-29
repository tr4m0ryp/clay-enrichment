"""
Layer 4: Email generation worker.

Generates personalized cold emails for high-priority contacts via Gemini.
Uses Postgres DB modules (src.db) for all data access.

Per task 014, the system prompt is locked to the per-campaign approved
voice via two campaign-level fields (schema 009) populated by the
Next-button flow (task 015): ``campaigns.email_style_profile`` (TEXT,
the voice anchor injected at the top of the prompt) and
``campaigns.banned_phrases`` (JSONB list[str], campaign-specific
phrases the model must never use, additive on top of the standard ban
list inside the prompt itself). When either field is empty defaults
from ``src.email.context`` are used. Gemini output is parsed through
the tolerant extractor + single-retry helper (F16) -- never
``json.loads`` directly.
"""

from __future__ import annotations

import asyncio
import logging

from src.db.campaigns import CampaignsDB
from src.db.companies import CompaniesDB
from src.db.contacts import ContactsDB
from src.db.emails import EmailsDB
from src.db.contact_campaigns import ContactCampaignsDB
from src.email.context import (
    build_contact_context,
    build_company_context,
    coerce_banned_phrases,
    entry_has_email_subject,
    format_banned_phrases,
    group_junction_entries_by_company,
    resolve_style_profile,
)
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)

_CYCLE_INTERVAL = 240  # seconds between worker cycles


async def generate_emails_for_company(
    company: dict,
    junction_entries: list[dict],
    config,
    gemini_client,
    campaigns_db: CampaignsDB,
    companies_db: CompaniesDB,
    contacts_db: ContactsDB,
    emails_db: EmailsDB,
    contact_campaigns_db: ContactCampaignsDB,
    campaign: dict,
) -> None:
    """Generate emails for junction entries at one company.

    ``campaign`` is the full campaigns row dict (must include
    ``email_style_profile`` and ``banned_phrases`` per schema 009).
    The voice anchor and banned-phrase list are rendered into the
    prompt for every email at this company.
    """
    campaign_id = str(campaign["id"])
    campaign_target = campaign.get("target_description", "") or ""
    style_profile = resolve_style_profile(campaign)
    banned_phrases = coerce_banned_phrases(campaign.get("banned_phrases"))
    banned_phrases_str = format_banned_phrases(banned_phrases)

    company_id = str(company["id"])
    company_name = company.get("name", "")

    company_body = await companies_db.get_body(company_id)
    company_context = build_company_context(company, company_body)

    contact_contexts: list[str] = []
    personalized_contexts: list[str] = []
    entry_meta: list[tuple[dict, str, str]] = []

    for entry in junction_entries:
        contact_id = entry.get("contact_id")
        if not contact_id:
            logger.warning(
                "Junction entry %s has no contact_id", entry["id"]
            )
            continue

        contact_id = str(contact_id)

        contact_row = await contacts_db._pool.fetchrow(
            "SELECT * FROM contacts WHERE id = $1",
            entry["contact_id"],
        )
        if not contact_row:
            logger.warning("Contact %s not found", contact_id)
            continue
        contact = dict(contact_row)

        contact_body = await contacts_db.get_body(contact_id)
        ctx = build_contact_context(contact, contact_body)
        contact_contexts.append(ctx)

        pc = entry.get("personalized_context", "") or ""
        personalized_contexts.append(pc)

        contact_name = contact.get("name", "")
        entry_meta.append((entry, contact_id, contact_name))

    if not entry_meta:
        return

    from src.email.prompts import GENERATE_EMAIL

    for i, (junction_entry, contact_id, contact_name) in enumerate(entry_meta):
        contact_ctx = contact_contexts[i] if i < len(contact_contexts) else ""
        pc = personalized_contexts[i] if i < len(personalized_contexts) else ""

        full_context = (
            f"{company_context}\n\n{contact_ctx}"
            if company_context else contact_ctx
        )

        # Voice anchor + campaign-specific bans go first so they set
        # the tone before any context the model can drift on.
        prompt = (
            GENERATE_EMAIL
            .replace("{email_style_profile}", style_profile)
            .replace("{banned_phrases}", banned_phrases_str)
            .replace(
                "{campaign_target}",
                campaign_target or "No specific campaign target provided.",
            )
            .replace("{contact_name}", contact_name or "there")
            .replace("{company_name}", company_name or "the company")
            .replace(
                "{contact_context}",
                full_context or "No specific context available.",
            )
            .replace(
                "{personalized_context}",
                pc or "No personalized context available.",
            )
        )

        async def _call(user_message: str) -> dict:
            return await gemini_client.generate(
                prompt=prompt,
                user_message=user_message,
                model=config.model_email_generation,
                json_mode=True,
                temperature=0.7,
            )

        base_user_message = (
            f"Generate a personalized cold email for {contact_name}"
            f" at {company_name}."
        )

        outcome = await retry_on_malformed_json(_call, base_user_message)
        if outcome is None:
            logger.error(
                "Email gen JSON unrecoverable for %s at %s",
                contact_name, company_name,
            )
            continue

        email_data, raw = outcome

        if isinstance(email_data, list):
            email_data = email_data[0] if email_data else {}
        if not isinstance(email_data, dict):
            logger.error(
                "Email gen non-dict output for %s at %s: %r",
                contact_name, company_name, type(email_data),
            )
            continue

        logger.info(
            "Generated email for %s at %s | in=%d out=%d tokens",
            contact_name, company_name,
            raw.get("input_tokens", 0), raw.get("output_tokens", 0),
        )

        junction_id = str(junction_entry["id"])
        subject = email_data.get("subject") or f"Outreach to {contact_name}"
        body = email_data.get("body") or ""

        await emails_db.create_email(
            subject=subject,
            contact_id=contact_id,
            campaign_id=campaign_id,
            body=body,
        )

        await contact_campaigns_db.update_email_subject(junction_id, subject)
        await contact_campaigns_db.update_outreach_status(
            junction_id, "Email Pending Review"
        )

        await contacts_db.update_contact(
            contact_id, status="Email Generated"
        )

        logger.info(
            "Created email for %s at %s: %s",
            contact_name, company_name, subject,
        )


async def email_gen_worker(
    config,
    gemini_client,
    campaigns_db: CampaignsDB,
    companies_db: CompaniesDB,
    contacts_db: ContactsDB,
    emails_db: EmailsDB,
    contact_campaigns_db: ContactCampaignsDB,
) -> None:
    """Continuous worker that generates emails for high-priority contacts.

    Polls the junction table for entries with score >=7 and no email
    subject yet. Groups by company and generates personalized emails
    using person research context plus the per-campaign locked voice.
    """
    logger.info("Email gen worker started")

    while True:
        try:
            active_campaigns = await campaigns_db.get_processable_campaigns()
            if not active_campaigns:
                logger.debug("No processable campaigns, sleeping")
                await asyncio.sleep(_CYCLE_INTERVAL)
                continue

            for campaign in active_campaigns:
                campaign_id = str(campaign["id"])
                campaign_name = campaign.get("name", "")

                entries = await contact_campaigns_db.get_high_priority(
                    campaign_id, min_score=7.0
                )

                pending = [e for e in entries if not entry_has_email_subject(e)]
                if not pending:
                    logger.debug(
                        "Campaign '%s': no pending high-priority entries",
                        campaign_name,
                    )
                    continue

                logger.info(
                    "Campaign '%s': %d high-priority entries need emails",
                    campaign_name, len(pending),
                )

                by_company = group_junction_entries_by_company(pending)
                for company_id, company_entries in by_company.items():
                    try:
                        company_row = await companies_db._pool.fetchrow(
                            "SELECT * FROM companies WHERE id = $1",
                            company_entries[0]["company_id"],
                        )
                        if not company_row:
                            logger.warning(
                                "Company %s not found", company_id[:8]
                            )
                            continue
                        company = dict(company_row)

                        await generate_emails_for_company(
                            company=company,
                            junction_entries=company_entries,
                            config=config,
                            gemini_client=gemini_client,
                            campaigns_db=campaigns_db,
                            companies_db=companies_db,
                            contacts_db=contacts_db,
                            emails_db=emails_db,
                            contact_campaigns_db=contact_campaigns_db,
                            campaign=campaign,
                        )
                    except Exception:
                        logger.error(
                            "Failed to generate emails for company %s",
                            company_id[:8], exc_info=True,
                        )

        except Exception:
            logger.error("Email gen worker cycle failed", exc_info=True)

        await asyncio.sleep(_CYCLE_INTERVAL)
