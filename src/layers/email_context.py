"""
Email context building helpers for the email generation layer.

Extracted from email_gen.py to keep each file under 300 lines.
Provides functions for converting Notion blocks to text, building
contact/company context strings, and creating Notion body blocks
from email text.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from src.notion.prop_helpers import (
    extract_title,
    extract_rich_text,
    extract_relation_ids,
    extract_number,
)

logger = logging.getLogger(__name__)


def blocks_to_text(blocks: list[dict]) -> str:
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


def text_to_body_blocks(text: str) -> list[dict]:
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


def build_contact_context(contact: dict, contact_body: str) -> str:
    """Build a text summary of a contact for the LLM prompt.

    Reads the structured Context property first (concise summary from
    person research). Falls back to full page body if Context is empty.

    Args:
        contact: Notion contact page object.
        contact_body: Plain text from the contact's page body
            (includes person research appended by person_research_worker).

    Returns:
        Formatted text block describing the contact.
    """
    name = extract_title(contact, "Name")
    job_title = extract_rich_text(contact, "Job Title")
    context = extract_rich_text(contact, "Context")
    parts = [f"Name: {name}"]
    if job_title:
        parts.append(f"Job Title: {job_title}")
    if context:
        parts.append(f"Context: {context}")
    if contact_body:
        parts.append(f"Person Research:\n{contact_body}")
    return "\n".join(parts)


def build_company_context(company: dict, company_body: str) -> str:
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


def group_junction_entries_by_company(
    entries: list[dict],
) -> dict[str, list[dict]]:
    """Group junction table entries by their Company relation ID.

    Args:
        entries: List of junction page objects from ContactCampaignsDB.

    Returns:
        Dict mapping company page ID to list of junction entries.
        Entries with no company relation are skipped.
    """
    by_company: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        company_ids = extract_relation_ids(entry, "Company")
        if company_ids:
            by_company[company_ids[0]].append(entry)
        else:
            logger.warning(
                "Junction entry %s has no company relation, skipping",
                entry.get("id", "unknown"),
            )
    return dict(by_company)


def entry_has_email_subject(entry: dict) -> bool:
    """Check whether a junction entry already has an email subject set.

    Args:
        entry: A junction page object.

    Returns:
        True if the Email Subject field is non-empty.
    """
    subject = extract_rich_text(entry, "Email Subject")
    return bool(subject and subject.strip())


def build_enhanced_prompt_context(
    company_context: str,
    contact_contexts: list[str],
    personalized_contexts: list[str],
    campaign_target: str,
) -> str:
    """Build the full context block inserted into the email prompt.

    Args:
        company_context: Formatted company info string.
        contact_contexts: List of formatted contact info strings.
        personalized_contexts: Per-contact personalized outreach angles.
        campaign_target: The campaign's target description.

    Returns:
        Combined context string for prompt interpolation.
    """
    parts = [f"## Company Context\n\n{company_context}\n"]
    parts.append("## Contacts\n")

    for i, (ct, pc) in enumerate(
        zip(contact_contexts, personalized_contexts), 1
    ):
        parts.append(f"### Contact {i}\n{ct}")
        if pc:
            parts.append(f"Personalized Outreach Angle: {pc}")
        parts.append("")

    return "\n".join(parts)
