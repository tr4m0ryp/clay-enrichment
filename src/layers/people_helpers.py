"""People layer helpers: email verification, name splitting, body blocks.

Extracted from people.py to keep files under the 300-line limit.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from src.discovery.smtp_verify import SMTPVerifier

logger = logging.getLogger(__name__)


def extract_domain(website_url: str) -> str:
    """Extract the bare domain from a company website URL.

    Handles URLs with or without scheme, strips 'www.' prefix.

    Args:
        website_url: Raw URL string (e.g. "https://www.example.com/about").

    Returns:
        Bare domain string (e.g. "example.com"), or empty string if
        the URL cannot be parsed.
    """
    if not website_url:
        return ""

    url = website_url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def split_name(full_name: str) -> tuple[str, str]:
    """Split a full name into first and last name.

    Args:
        full_name: Full name string.

    Returns:
        Tuple of (first_name, last_name). Last name may be empty for
        single-word names.
    """
    parts = full_name.strip().split()
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], " ".join(parts[1:]))


def build_contact_body_blocks(
    contact_data: dict,
    company_name: str,
    email: str,
    verified: bool,
) -> list[dict]:
    """Build Notion page body blocks summarising the contact context.

    Args:
        contact_data: Parsed contact dict from Gemini.
        company_name: The company this contact belongs to.
        email: The selected email address.
        verified: Whether the email was verified via SMTP.

    Returns:
        List of Notion block objects for the contact page body.
    """
    verification_label = "Verified" if verified else "Unverified (best guess)"
    lines = [
        f"Contact discovered at {company_name}",
        f"Title: {contact_data.get('title', 'Unknown')}",
        f"Email: {email} ({verification_label})",
    ]
    linkedin = contact_data.get("linkedin_url", "")
    if linkedin:
        lines.append(f"LinkedIn: {linkedin}")

    blocks = []
    for line in lines:
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": line}}]
                },
            }
        )
    return blocks


async def verify_email_waterfall(
    smtp_verifier: SMTPVerifier,
    permutations: list[str],
) -> tuple[str, bool]:
    """Try email permutations in order, stop at first verified.

    Args:
        smtp_verifier: The SMTP verification client.
        permutations: Ordered list of email address candidates.

    Returns:
        Tuple of (email, verified). If none verify, returns the first
        permutation marked as unverified.
    """
    if not permutations:
        return ("", False)

    for email in permutations:
        try:
            result = await smtp_verifier.verify(email)
            if result.valid:
                logger.info("Email verified: %s (method=%s)", email, result.method)
                return (email, True)
        except Exception as exc:
            logger.warning("SMTP verify error for %s: %s", email, exc)
            continue

    # No email verified -- return first permutation as best guess
    return (permutations[0], False)
