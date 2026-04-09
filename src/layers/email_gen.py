"""
Layer 4: Email generation worker.

Sources high-priority contacts (score >=8) from the Contact-Campaign
junction table, generates personalized outreach emails using person
research + company enrichment + campaign-specific context via Gemini,
and creates email records in Notion with "Pending Review" status.
"""

from __future__ import annotations

import asyncio
import json
import logging

from src.notion.prop_helpers import (
    extract_title,
    extract_rich_text,
    extract_relation_ids,
    select_prop,
)
from src.layers.email_context import (
    blocks_to_text,
    text_to_body_blocks,
    build_contact_context,
    build_company_context,
    build_enhanced_prompt_context,
    group_junction_entries_by_company,
    entry_has_email_subject,
)

logger = logging.getLogger(__name__)

_CYCLE_INTERVAL = 240  # seconds between worker cycles


async def _load_campaign_target(campaigns_db, campaign_id: str) -> str:
    """Load the target description for a campaign by page ID."""
    campaign_pages = await campaigns_db._client.query_database(
        campaigns_db.db_id,
        filter_obj={"property": "Name", "title": {"is_not_empty": True}},
    )
    for cp in campaign_pages:
        if cp["id"] == campaign_id:
            return extract_rich_text(cp, "Target Description")
    return ""


async def generate_emails_for_company(
    company_page: dict,
    junction_entries: list[dict],
    config,
    gemini_client,
    notion_client,
    campaigns_db,
    contacts_db,
    emails_db,
    contact_campaigns_db,
    campaign_id: str,
    campaign_target: str,
):
    """Generate emails for junction entries at one company.

    Loads company enrichment data and per-contact person research,
    calls Gemini with enhanced context, then creates email records
    and updates junction + contact statuses.

    Args:
        company_page: The Notion company page object.
        junction_entries: Junction entries for contacts at this company.
        config: Application config object.
        gemini_client: GeminiClient instance.
        notion_client: NotionClient for raw API calls.
        campaigns_db: CampaignsDB instance.
        contacts_db: ContactsDB instance.
        emails_db: EmailsDB instance.
        contact_campaigns_db: ContactCampaignsDB instance.
        campaign_id: The campaign page ID.
        campaign_target: Campaign target description text.
    """
    company_id = company_page["id"]
    company_name = extract_title(company_page, "Name")

    # Load company page body for enrichment context
    company_blocks = await notion_client.get_page_body(company_id)
    company_body = blocks_to_text(company_blocks)
    company_context = build_company_context(company_page, company_body)

    # Build per-contact context from junction entries
    contact_contexts = []
    personalized_contexts = []
    entry_meta = []  # (junction_entry, contact_id, contact_name)

    for entry in junction_entries:
        contact_ids = extract_relation_ids(entry, "Contact")
        if not contact_ids:
            logger.warning(
                "Junction entry %s has no contact relation", entry["id"]
            )
            continue

        contact_id = contact_ids[0]
        contact_page = await notion_client._call(
            notion_client._sdk.pages.retrieve, page_id=contact_id,
        )

        # Load contact page body (contains person research)
        contact_blocks = await notion_client.get_page_body(contact_id)
        contact_body = blocks_to_text(contact_blocks)
        ctx = build_contact_context(contact_page, contact_body)
        contact_contexts.append(ctx)

        # Get personalized context from junction record
        pc = extract_rich_text(entry, "Personalized Context")
        personalized_contexts.append(pc)

        contact_name = extract_title(contact_page, "Name")
        entry_meta.append((entry, contact_id, contact_name))

    if not entry_meta:
        return

    # Build the combined context block for the prompt
    contacts_block = build_enhanced_prompt_context(
        company_context, contact_contexts, personalized_contexts,
        campaign_target,
    )

    # Interpolate the prompt with campaign target and contacts.
    from src.prompts.email import GENERATE_EMAIL

    prompt = GENERATE_EMAIL.replace(
        "{campaign_target}",
        campaign_target or "No specific campaign target provided.",
    ).replace(
        "{contacts}",
        contacts_block,
    )

    # Call Gemini
    result = await gemini_client.generate(
        prompt=prompt,
        user_message="Generate personalized emails for each contact listed above.",
        model=config.model_email_generation,
        json_mode=True,
        temperature=0.7,
    )

    # Parse response
    try:
        emails = json.loads(result["text"])
    except json.JSONDecodeError:
        logger.error(
            "Failed to parse email generation response for company %s: %s",
            company_name, result["text"][:500],
        )
        return

    if not isinstance(emails, list):
        emails = [emails]

    logger.info(
        "Generated %d emails for %s | in=%d out=%d tokens",
        len(emails), company_name,
        result["input_tokens"], result["output_tokens"],
    )

    # Create email records and update statuses
    for i, email_data in enumerate(emails):
        if i >= len(entry_meta):
            logger.warning(
                "More emails returned than contacts for %s, skipping extra",
                company_name,
            )
            break

        junction_entry, contact_id, contact_name = entry_meta[i]
        junction_id = junction_entry["id"]
        subject = email_data.get("subject", f"Outreach to {contact_name}")
        body = email_data.get("body", "")
        body_blocks = text_to_body_blocks(body)

        # Create email record in Emails DB
        await emails_db.create_email(
            subject=subject,
            contact_id=contact_id,
            campaign_id=campaign_id,
            body_blocks=body_blocks,
        )

        # Update junction record with email subject and outreach status
        await contact_campaigns_db.update_email_subject(junction_id, subject)
        await contact_campaigns_db.update_outreach_status(
            junction_id, "Email Pending Review"
        )

        # Update contact status
        await contacts_db.update_contact(
            contact_id, {"Status": select_prop("Email Generated")}
        )

        logger.info(
            "Created email for %s at %s: %s",
            contact_name, company_name, subject,
        )


async def email_gen_worker(
    config,
    gemini_client,
    notion_client,
    contacts_db,
    campaigns_db,
    emails_db,
    contact_campaigns_db,
):
    """Continuous worker that generates emails for high-priority contacts.

    Polls the junction table for entries with score >=8 and no email
    subject yet. Groups by company and generates personalized emails
    using person research context.

    Args:
        config: Application config object.
        gemini_client: GeminiClient instance.
        notion_client: NotionClient for raw API calls (page body reads).
        contacts_db: ContactsDB instance.
        campaigns_db: CampaignsDB instance.
        emails_db: EmailsDB instance.
        contact_campaigns_db: ContactCampaignsDB instance.
    """
    logger.info("Email gen worker started")

    while True:
        try:
            # Get all active campaigns
            active_campaigns = await campaigns_db.get_active_campaigns()
            if not active_campaigns:
                logger.debug("No active campaigns, sleeping")
                await asyncio.sleep(_CYCLE_INTERVAL)
                continue

            for campaign in active_campaigns:
                campaign_id = campaign["id"]
                campaign_name = extract_title(campaign, "Name")

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
                        company_page = await notion_client._call(
                            notion_client._sdk.pages.retrieve,
                            page_id=company_id,
                        )
                        await generate_emails_for_company(
                            company_page=company_page,
                            junction_entries=company_entries,
                            config=config,
                            gemini_client=gemini_client,
                            notion_client=notion_client,
                            campaigns_db=campaigns_db,
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
