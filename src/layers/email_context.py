"""
Email context building helpers for the email generation layer.

Extracted from email_gen.py to keep each file under 300 lines.
Provides functions for building contact/company context strings
from flat Postgres dicts, and grouping junction entries by company.
"""

from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def build_contact_context(contact: dict, contact_body: str) -> str:
    """Build a text summary of a contact for the LLM prompt.

    Reads the structured context field first (concise summary from
    person research). Falls back to full body text if context is empty.

    Args:
        contact: Flat dict from contacts table row.
        contact_body: Plain text body from the contact record.

    Returns:
        Formatted text block describing the contact.
    """
    name = contact.get("name", "")
    job_title = contact.get("job_title", "")
    context = contact.get("context", "")
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
        company: Flat dict from companies table row.
        company_body: Plain text body from the company record.

    Returns:
        Formatted text block describing the company.
    """
    name = company.get("name", "")
    parts = [f"Company: {name}"]

    website = company.get("website", "")
    if website:
        parts.append(f"Website: {website}")

    industry = company.get("industry", "")
    if industry:
        parts.append(f"Industry: {industry}")

    location = company.get("location", "")
    if location:
        parts.append(f"Location: {location}")

    size = company.get("size", "")
    if size:
        parts.append(f"Size: {size}")

    if company_body:
        parts.append(f"Enrichment Data:\n{company_body}")

    return "\n".join(parts)


def group_junction_entries_by_company(
    entries: list[dict],
) -> dict[str, list[dict]]:
    """Group junction table entries by their company_id.

    Args:
        entries: List of flat dicts from contact_campaigns table.

    Returns:
        Dict mapping company_id string to list of junction entries.
        Entries with no company_id are skipped.
    """
    by_company: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        company_id = entry.get("company_id")
        if company_id:
            by_company[str(company_id)].append(entry)
        else:
            logger.warning(
                "Junction entry %s has no company_id, skipping",
                entry.get("id", "unknown"),
            )
    return dict(by_company)


def entry_has_email_subject(entry: dict) -> bool:
    """Check whether a junction entry already has an email subject set.

    Args:
        entry: A flat dict from contact_campaigns table.

    Returns:
        True if the email_subject field is non-empty.
    """
    subject = entry.get("email_subject", "")
    return bool(subject and subject.strip())
