"""
Email context building helpers for the email generation layer.

Extracted from email_gen.py to keep each file under 300 lines.
Provides functions for building contact/company context strings
from flat Postgres dicts, grouping junction entries by company, and
(per task 014) resolving the per-campaign voice anchor and banned
phrases that prepend the email-gen prompt.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from src.utils.json_extract import extract_json

logger = logging.getLogger(__name__)

# Mirrors the existing prompt's tone for campaigns predating the
# redesign or finalized before the Next-button flow populated
# email_style_profile. Kept intentionally short -- the prompt itself
# carries the per-part rules; this is just the voice anchor.
DEFAULT_STYLE_PROFILE: str = (
    "Direct, problem-focused B2B voice. Short paragraphs. No corporate "
    "filler. Lead with a recipient-specific observation. Mirror the "
    "prospect's own language. One clear CTA. Never use 'I hope this "
    "finds you well' or 'innovative'."
)

_DEFAULT_BANNED_PHRASES_RENDER: str = (
    "(none beyond the standard ban list in the prompt below)"
)


def coerce_banned_phrases(raw: Any) -> list[str]:
    """Normalize the campaign row's ``banned_phrases`` into list[str].

    asyncpg returns JSONB columns as JSON strings unless a custom codec
    is registered (the project deliberately keeps no codec). The value
    can be ``None``, a list (some setups decode jsonb), or a JSON-
    encoded string like ``'["foo", "bar"]'`` -- the common case.

    Any other shape is treated as no bans. ``extract_json`` is used to
    deserialize the string form because it tolerates malformed input
    without raising.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if str(p).strip()]
    if isinstance(raw, str):
        if not raw.strip():
            return []
        parsed = extract_json(raw)
        if isinstance(parsed, list):
            return [str(p).strip() for p in parsed if str(p).strip()]
        return []
    return []


def format_banned_phrases(phrases: list[str]) -> str:
    """Render the banned-phrases list for inclusion in the prompt.

    Returns a human-readable bullet list. When ``phrases`` is empty the
    placeholder string explicitly tells the model that only the
    standard ban list (already inside the prompt) applies.
    """
    cleaned = [p.strip() for p in phrases if p and p.strip()]
    if not cleaned:
        return _DEFAULT_BANNED_PHRASES_RENDER
    return "- " + "\n- ".join(cleaned)


def resolve_style_profile(campaign: dict) -> str:
    """Return the campaign's voice anchor, falling back to the default.

    Reads ``campaign['email_style_profile']`` (TEXT column added in
    schema 009) and returns the stripped value, or
    ``DEFAULT_STYLE_PROFILE`` when the field is empty or missing.
    """
    raw = campaign.get("email_style_profile") or ""
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped:
            return stripped
    return DEFAULT_STYLE_PROFILE


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
