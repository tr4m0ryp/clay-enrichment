"""
Layer 4: Email generation worker.

Generates personalized cold emails for high-priority contacts via Gemini.
Uses Postgres DB modules (src.db) for all data access.
"""

from __future__ import annotations

import asyncio
import json
import logging

from src.db.campaigns import CampaignsDB
from src.db.companies import CompaniesDB
from src.db.contacts import ContactsDB
from src.db.emails import EmailsDB
from src.db.contact_campaigns import ContactCampaignsDB
from src.layers.email_context import (
    build_contact_context,
    build_company_context,
    group_junction_entries_by_company,
    entry_has_email_subject,
)

logger = logging.getLogger(__name__)

_CYCLE_INTERVAL = 240  # seconds between worker cycles


async def _load_campaign_target(campaigns_db: CampaignsDB, campaign_id: str) -> str:
    """Load the target description for a campaign by page ID."""
    campaigns = await campaigns_db.get_processable_campaigns()
    for cp in campaigns:
        if str(cp["id"]) == str(campaign_id):
            return cp.get("target_description", "")
    return ""


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
    campaign_id: str,
    campaign_target: str,
) -> None:
    """Generate emails for junction entries at one company."""
    company_id = str(company["id"])
    company_name = company.get("name", "")

    # Load company body text for enrichment context
    company_body = await companies_db.get_body(company_id)
    company_context = build_company_context(company, company_body)

    # Build per-contact context from junction entries
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

        # Fetch contact row
        contact_row = await contacts_db._pool.fetchrow(
            "SELECT * FROM contacts WHERE id = $1",
            entry["contact_id"],
        )
        if not contact_row:
            logger.warning("Contact %s not found", contact_id)
            continue
        contact = dict(contact_row)

        # Load contact body (contains person research)
        contact_body = await contacts_db.get_body(contact_id)
        ctx = build_contact_context(contact, contact_body)
        contact_contexts.append(ctx)

        # Get personalized context from junction record
        pc = entry.get("personalized_context", "") or ""
        personalized_contexts.append(pc)

        contact_name = contact.get("name", "")
        entry_meta.append((entry, contact_id, contact_name))

    if not entry_meta:
        return

    from src.prompts.email import GENERATE_EMAIL

    # Generate one email per contact using individual context
    for i, (junction_entry, contact_id, contact_name) in enumerate(entry_meta):
        contact_ctx = contact_contexts[i] if i < len(contact_contexts) else ""
        pc = personalized_contexts[i] if i < len(personalized_contexts) else ""

        # Combine company enrichment with contact-level context
        full_context = (
            f"{company_context}\n\n{contact_ctx}"
            if company_context else contact_ctx
        )

        # Interpolate per-contact prompt variables
        prompt = GENERATE_EMAIL.replace(
            "{campaign_target}",
            campaign_target or "No specific campaign target provided.",
        ).replace(
            "{contact_name}", contact_name or "there",
        ).replace(
            "{company_name}", company_name or "the company",
        ).replace(
            "{contact_context}",
            full_context or "No specific context available.",
        ).replace(
            "{personalized_context}",
            pc or "No personalized context available.",
        )

        # Call Gemini for this contact
        result = await gemini_client.generate(
            prompt=prompt,
            user_message=(
                f"Generate a personalized cold email for {contact_name}"
                f" at {company_name}."
            ),
            model=config.model_email_generation,
            json_mode=True,
            temperature=0.7,
        )

        # Parse response
        try:
            email_data = json.loads(result["text"])
        except json.JSONDecodeError:
            logger.error(
                "Failed to parse email response for %s at %s: %s",
                contact_name, company_name, result["text"][:500],
            )
            continue

        if isinstance(email_data, list):
            email_data = email_data[0] if email_data else {}

        logger.info(
            "Generated email for %s at %s | in=%d out=%d tokens",
            contact_name, company_name,
            result["input_tokens"], result["output_tokens"],
        )

        junction_id = str(junction_entry["id"])
        subject = email_data.get("subject", f"Outreach to {contact_name}")
        body = email_data.get("body", "")

        # Create email record in Emails DB (body stored as TEXT)
        await emails_db.create_email(
            subject=subject,
            contact_id=contact_id,
            campaign_id=campaign_id,
            body=body,
        )

        # Update junction record with email subject and outreach status
        await contact_campaigns_db.update_email_subject(junction_id, subject)
        await contact_campaigns_db.update_outreach_status(
            junction_id, "Email Pending Review"
        )

        # Update contact status
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
    using person research context.

    Args:
        config: Application config object.
        gemini_client: GeminiClient instance.
        campaigns_db: CampaignsDB instance.
        companies_db: CompaniesDB instance.
        contacts_db: ContactsDB instance.
        emails_db: EmailsDB instance.
        contact_campaigns_db: ContactCampaignsDB instance.
    """
    logger.info("Email gen worker started")

    while True:
        try:
            # Get all processable campaigns (Active + Paused + Completed)
            active_campaigns = await campaigns_db.get_processable_campaigns()
            if not active_campaigns:
                logger.debug("No processable campaigns, sleeping")
                await asyncio.sleep(_CYCLE_INTERVAL)
                continue

            for campaign in active_campaigns:
                campaign_id = str(campaign["id"])
                campaign_name = campaign.get("name", "")

                # Query junction table for high-priority entries
                entries = await contact_campaigns_db.get_high_priority(
                    campaign_id, min_score=7.0
                )

                # Filter to entries without an email subject yet
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

                campaign_target = await _load_campaign_target(
                    campaigns_db, campaign_id
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
                            campaign_id=campaign_id,
                            campaign_target=campaign_target,
                        )
                    except Exception:
                        logger.error(
                            "Failed to generate emails for company %s",
                            company_id[:8], exc_info=True,
                        )

        except Exception:
            logger.error("Email gen worker cycle failed", exc_info=True)

        await asyncio.sleep(_CYCLE_INTERVAL)
