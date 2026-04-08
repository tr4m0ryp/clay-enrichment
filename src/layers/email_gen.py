"""
Layer 4: Email generation worker.

Picks up contacts with status "Enriched", generates personalized outreach
emails using company + contact context via Gemini, and creates email records
in Notion with "Pending Review" status. Never sends emails.
"""

import asyncio
import json
import logging
from collections import defaultdict

from src.notion.prop_helpers import (
    extract_title,
    extract_rich_text,
    extract_relation_ids,
    select_prop,
)

logger = logging.getLogger(__name__)


def group_contacts_by_company(contacts: list[dict]) -> dict[str, list[dict]]:
    """Group contact pages by their Company relation ID.

    Args:
        contacts: List of Notion contact page objects.

    Returns:
        Dict mapping company page ID to list of contact pages.
        Contacts with no company relation are skipped.
    """
    by_company: dict[str, list[dict]] = defaultdict(list)
    for contact in contacts:
        company_ids = extract_relation_ids(contact, "Company")
        if company_ids:
            by_company[company_ids[0]].append(contact)
        else:
            logger.warning(
                "Contact %s has no company relation, skipping",
                contact.get("id", "unknown"),
            )
    return dict(by_company)


def _blocks_to_text(blocks: list[dict]) -> str:
    """Extract plain text from Notion block objects.

    Concatenates paragraph text from page body blocks into a single
    string for use as LLM context.

    Args:
        blocks: List of Notion block objects.

    Returns:
        Plain text content of the blocks.
    """
    parts = []
    for block in blocks:
        block_type = block.get("type", "")
        type_data = block.get(block_type, {})
        rich_texts = type_data.get("rich_text", [])
        text = "".join(rt.get("plain_text", "") for rt in rich_texts)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _text_to_body_blocks(text: str) -> list[dict]:
    """Convert plain text into Notion paragraph blocks.

    Splits on double newlines to create separate paragraphs.
    Single newlines within a paragraph are preserved.

    Args:
        text: The email body text.

    Returns:
        List of Notion paragraph block dicts.
    """
    paragraphs = text.split("\n\n")
    blocks = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": para[:2000]}}],
            },
        })
    return blocks


def _build_contact_context(contact: dict, contact_body: str) -> str:
    """Build a text summary of a contact for the LLM prompt.

    Args:
        contact: Notion contact page object.
        contact_body: Plain text from the contact's page body.

    Returns:
        Formatted text block describing the contact.
    """
    name = extract_title(contact, "Name")
    job_title = extract_rich_text(contact, "Job Title")
    parts = [f"Name: {name}"]
    if job_title:
        parts.append(f"Job Title: {job_title}")
    if contact_body:
        parts.append(f"Profile:\n{contact_body}")
    return "\n".join(parts)


def _build_company_context(company: dict, company_body: str) -> str:
    """Build a text summary of a company for the LLM prompt.

    Args:
        company: Notion company page object.
        company_body: Plain text from the company's page body.

    Returns:
        Formatted text block describing the company.
    """
    name = extract_title(company, "Name")
    parts = [f"Company: {name}"]

    website = company.get("properties", {}).get("Website", {}).get("url", "")
    if website:
        parts.append(f"Website: {website}")

    industry = company.get("properties", {}).get("Industry", {})
    sel = industry.get("select")
    if sel and isinstance(sel, dict):
        parts.append(f"Industry: {sel.get('name', '')}")

    location = extract_rich_text(company, "Location")
    if location:
        parts.append(f"Location: {location}")

    size = extract_rich_text(company, "Size")
    if size:
        parts.append(f"Size: {size}")

    if company_body:
        parts.append(f"Enrichment Data:\n{company_body}")

    return "\n".join(parts)


async def generate_emails_for_company(
    company_page: dict,
    company_contacts: list[dict],
    config,
    gemini_client,
    notion_client,
    campaigns_db,
    contacts_db,
    emails_db,
):
    """Generate emails for all contacts at one company.

    Loads company enrichment data, builds shared context, calls Gemini
    once with all contacts batched, then creates email records in Notion.

    Args:
        company_page: The Notion company page object.
        company_contacts: Contact pages at this company.
        config: Application config object.
        gemini_client: GeminiClient instance.
        notion_client: NotionClient for raw API calls.
        campaigns_db: CampaignsDB instance.
        contacts_db: ContactsDB instance.
        emails_db: EmailsDB instance.
    """
    company_id = company_page["id"]
    company_name = extract_title(company_page, "Name")

    # Load company page body for enrichment context
    company_blocks = await notion_client.get_page_body(company_id)
    company_body = _blocks_to_text(company_blocks)
    company_context = _build_company_context(company_page, company_body)

    # Load campaign target description (from first contact's campaign)
    campaign_target = ""
    first_contact = company_contacts[0]
    campaign_ids = extract_relation_ids(first_contact, "Campaign")
    campaign_id = campaign_ids[0] if campaign_ids else ""
    if campaign_id:
        campaign_pages = await campaigns_db._client.query_database(
            campaigns_db.db_id,
            filter_obj={"property": "Name", "title": {"is_not_empty": True}},
        )
        for cp in campaign_pages:
            if cp["id"] == campaign_id:
                campaign_target = extract_rich_text(cp, "Target Description")
                break

    # Build per-contact context and collect metadata
    contact_texts = []
    contact_meta = []  # (contact_page, contact_name)
    for contact in company_contacts:
        contact_id = contact["id"]
        contact_blocks = await notion_client.get_page_body(contact_id)
        contact_body = _blocks_to_text(contact_blocks)
        ctx = _build_contact_context(contact, contact_body)
        contact_texts.append(ctx)
        contact_meta.append((contact, extract_title(contact, "Name")))

    # Build the combined contacts block for the prompt
    contacts_block = f"## Company Context\n\n{company_context}\n\n## Contacts\n\n"
    for i, ct in enumerate(contact_texts, 1):
        contacts_block += f"### Contact {i}\n{ct}\n\n"

    # Interpolate the prompt with campaign target and contacts.
    # Uses replace() instead of .format() because the prompt template
    # contains literal JSON braces that would conflict with str.format().
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
            company_name,
            result["text"][:500],
        )
        return

    if not isinstance(emails, list):
        emails = [emails]

    logger.info(
        "Generated %d emails for %s | in=%d out=%d tokens",
        len(emails),
        company_name,
        result["input_tokens"],
        result["output_tokens"],
    )

    # Create email records and update contact statuses
    for i, email_data in enumerate(emails):
        if i >= len(contact_meta):
            logger.warning(
                "More emails returned than contacts for %s, skipping extra",
                company_name,
            )
            break

        contact_page, contact_name = contact_meta[i]
        contact_id = contact_page["id"]
        subject = email_data.get("subject", f"Outreach to {contact_name}")
        body = email_data.get("body", "")

        body_blocks = _text_to_body_blocks(body)

        # Determine campaign ID for this contact
        c_campaign_ids = extract_relation_ids(contact_page, "Campaign")
        c_campaign_id = c_campaign_ids[0] if c_campaign_ids else campaign_id

        await emails_db.create_email(
            subject=subject,
            contact_id=contact_id,
            campaign_id=c_campaign_id,
            body_blocks=body_blocks,
        )

        await contacts_db.update_contact(
            contact_id, {"Status": select_prop("Email Generated")}
        )

        logger.info(
            "Created email for %s at %s: %s",
            contact_name,
            company_name,
            subject,
        )


async def email_gen_worker(config, gemini_client, notion_client, notion_dbs):
    """Continuous worker that generates emails for enriched contacts.

    Polls for contacts with status "Enriched", groups them by company,
    and generates personalized outreach emails. Runs indefinitely with
    a 4-minute sleep between cycles.

    Args:
        config: Application config object.
        gemini_client: GeminiClient instance.
        notion_client: NotionClient for raw API calls (page body reads).
        notion_dbs: Dict or namespace with campaigns, contacts, emails DB instances.
            Expected keys/attrs: "campaigns", "contacts", "emails".
    """
    campaigns_db = notion_dbs["campaigns"] if isinstance(notion_dbs, dict) else notion_dbs.campaigns
    contacts_db = notion_dbs["contacts"] if isinstance(notion_dbs, dict) else notion_dbs.contacts
    emails_db = notion_dbs["emails"] if isinstance(notion_dbs, dict) else notion_dbs.emails

    while True:
        try:
            contacts = await contacts_db.get_contacts_needing_emails()
            if not contacts:
                logger.debug("No contacts needing emails, sleeping")
                await asyncio.sleep(240)
                continue

            logger.info("Found %d contacts needing emails", len(contacts))
            by_company = group_contacts_by_company(contacts)

            for company_id, company_contacts in by_company.items():
                try:
                    # Load the company page
                    company_page = await notion_client._call(
                        notion_client._sdk.pages.retrieve,
                        page_id=company_id,
                    )
                    await generate_emails_for_company(
                        company_page=company_page,
                        company_contacts=company_contacts,
                        config=config,
                        gemini_client=gemini_client,
                        notion_client=notion_client,
                        campaigns_db=campaigns_db,
                        contacts_db=contacts_db,
                        emails_db=emails_db,
                    )
                except Exception:
                    company_name = company_id[:8]
                    logger.error(
                        "Failed to generate emails for company %s",
                        company_name,
                        exc_info=True,
                    )

        except Exception:
            logger.error("Email gen worker cycle failed", exc_info=True)

        await asyncio.sleep(240)
