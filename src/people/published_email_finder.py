"""Gemini-grounded published-email finder.

Per research F13/F14: a material fraction of decision-maker emails are
published openly (team pages, conference bios, GitHub commits, press
releases). One Gemini grounded call per (name, domain) catches these
directly, skipping Hunter / pattern construction.

This module is a pure call -- no caching layer here; the people worker
decides when to invoke this and how to persist the result. Off-domain
matches are rejected at the function boundary so the caller can rely on
either an empty string or a verified-domain match.

Public surface:
    ``async find_published_email(gemini_client, first_name, last_name,
    domain, company_name) -> tuple[str, str]``
        Returns ``(email, confidence)`` where ``confidence`` is one of
        ``"high"``, ``"medium"``, ``"low"``, ``"none"``. Empty inputs
        (no first_name OR no domain) and any parse / validation failure
        return ``("", "none")`` without surprising the caller.

Per F16, the prompt follows the Strict Prompt Template verbatim so its
output structure is invariant from Gemini 3 Pro down through Gemini 2.5
Flash. JSON parsing is routed through ``extract_json`` /
``retry_on_malformed_json`` (per task 002) -- never ``json.loads``
directly.
"""

from __future__ import annotations

import logging

from src.gemini.client import GeminiClient
from src.prompts.base_context import build_system_prompt
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)


PROMPT = build_system_prompt("""\
## Task
Find {first_name} {last_name}'s work email at {company_name} ({domain}) by searching the open web.

## Inputs
- {first_name}: contact's first name (string, e.g. "Jane")
- {last_name}: contact's last name (string, e.g. "Smith")
- {company_name}: company name (string, e.g. "Patagonia")
- {domain}: company domain (string, e.g. "patagonia.com")

## Output Format -- EXACT
Return ONLY a valid JSON object matching this schema. No markdown fences. No prose before or after. No explanation. No preamble.

{
  "email": "string -- the discovered email address, lowercased; empty string if not found in any public source",
  "confidence": "string -- one of: high, medium, low, none",
  "source_url": "string -- URL where the email was found; empty string if not found",
  "source_quote": "string -- the literal sentence or fragment from the source that contained the email; empty string if not found"
}

### Field-by-field rules
- email: lowercase, exact match for the contact at the specified domain. NEVER guess or construct from a pattern -- only return what is literally published on a public web source. If you cannot find a published email, set to "". NEVER write "Unknown", "N/A", "No data found", or any sentinel string.
- confidence: one of the four exact strings below. NEVER use any other value.
  - "high": exact match on the contact's name AND domain, found on a primary source (company team page, official bio, conference speaker page, press release).
  - "medium": exact match on name AND domain, found on a secondary source (LinkedIn cached, blog interview, podcast guest page).
  - "low": partial match (e.g. just `firstname@domain` without explicit attribution).
  - "none": no published email found.
- source_url: the URL from the grounded search citations where the email appeared. Empty string "" if confidence is "none".
- source_quote: literal fragment containing the email, max 300 chars. Empty string "" if confidence is "none".

## Process -- follow exactly
1. Search Google for the contact's name + company name + "email" / "contact".
2. Search Google for the contact's name + domain + "email".
3. Inspect any returned LinkedIn / GitHub / press release / company team page hits.
4. If an email at the target domain is literally written on one of those pages, return it with the appropriate confidence.
5. If no match, return all-empty fields with confidence "none".

## Hard Rules (model MUST obey regardless of capability)
- Output is JSON ONLY. No prose before or after. No markdown fences.
- NEVER fabricate an email. If you do not find one literally written on a public source, return "" with confidence "none".
- NEVER use email permutation patterns (firstname.lastname@) and report them as published. Pattern construction is the caller's responsibility, not yours.
- Empty values: "" for missing strings. Never use sentinel strings like "Unknown" or "N/A".
- Never use emojis.
- Never include keys not in the schema. Never omit keys in the schema.
- Never include comments inside the JSON.

## Output Examples
### Good output (found on a team page)
{"email": "jane.smith@patagonia.com", "confidence": "high", "source_url": "https://patagonia.com/team", "source_quote": "Jane Smith, Head of Sustainability -- jane.smith@patagonia.com"}

### Good output (not found)
{"email": "", "confidence": "none", "source_url": "", "source_quote": ""}

### Bad outputs (do NOT do these)
- {"email": "jane.smith@patagonia.com", "confidence": "high", "source_url": "(constructed from firstname.lastname pattern)"}    (pattern guessing)
- "Here is the JSON: {...}"                                                                                                     (prose before)
- "```json\\n{...}\\n```"                                                                                                         (markdown fence)
- {"email": "Unknown"}                                                                                                          (sentinel string instead of "")
- {"email": "...", "confidence": "maybe"}                                                                                       (confidence not in allowed set)
""")


_VALID_CONFIDENCES: frozenset[str] = frozenset({"high", "medium", "low", "none"})


async def find_published_email(
    gemini_client: GeminiClient,
    first_name: str,
    last_name: str,
    domain: str,
    company_name: str,
) -> tuple[str, str]:
    """Return ``(email, confidence)`` for the contact's published email.

    ``confidence`` is one of ``"high"``, ``"medium"``, ``"low"``,
    ``"none"``. Empty email plus ``"none"`` is returned when:
        - ``first_name`` or ``domain`` is empty (no Gemini call is made),
        - the model returns malformed JSON twice in a row,
        - the parsed payload is not a dict,
        - the email does not look like an email,
        - the email is at a different domain than ``domain`` (off-domain
          matches are filtered here so the caller can rely on a strict
          domain guarantee on non-empty results),
        - the confidence is not in the allowed set.

    Args:
        gemini_client: Pool-backed Gemini client (see
            ``src/gemini/client.py``).
        first_name: Contact's first name.
        last_name: Contact's last name. May be empty.
        domain: Company domain (e.g. ``"patagonia.com"``). Required.
        company_name: Company display name. Falls back to ``domain``
            when empty so the prompt still reads naturally.

    Returns:
        Tuple ``(email, confidence)``. ``email`` is lowercase and at
        ``domain`` on success, or the empty string. ``confidence`` is
        always one of the four allowed strings.
    """
    if not first_name or not domain:
        return "", "none"

    rendered_prompt = (
        PROMPT
        .replace("{first_name}", first_name)
        .replace("{last_name}", last_name or "")
        .replace("{domain}", domain)
        .replace("{company_name}", company_name or domain)
    )

    async def _call(user_message: str) -> dict:
        return await gemini_client.generate(
            prompt=rendered_prompt,
            user_message=user_message,
            grounding=True,
            json_mode=True,
        )

    base_user_message = (
        f"Find the public email address for {first_name} {last_name or ''} "
        f"at {company_name or domain} ({domain})."
    ).strip()

    result = await retry_on_malformed_json(_call, base_user_message)
    if result is None:
        return "", "none"

    parsed, _raw = result
    if not isinstance(parsed, dict):
        logger.warning(
            "published_email_finder: non-dict parsed output for %s @ %s: %r",
            first_name, domain, parsed,
        )
        return "", "none"

    email = _coerce_email(parsed.get("email"))
    confidence = _coerce_confidence(parsed.get("confidence"))

    if not email or not _looks_like_email(email):
        return "", "none"

    if not email.endswith("@" + domain.lower()):
        # Reject off-domain matches: the model sometimes returns an
        # email at a vendor / personal domain instead of the target
        # company's domain. Caller relies on a strict domain guarantee.
        logger.info(
            "published_email_finder: rejecting off-domain match %s "
            "for target domain %s",
            email, domain,
        )
        return "", "none"

    return email, confidence


def _coerce_email(value: object) -> str:
    """Return ``value`` as a stripped, lowercased email string.

    Non-string inputs and the literal sentinel ``"unknown"`` (case
    insensitive, plus a few common variants) collapse to the empty
    string so the caller never sees a sentinel where a real email
    is expected.
    """
    if not isinstance(value, str):
        return ""
    cleaned = value.strip().lower()
    if cleaned in {"unknown", "n/a", "none", "no data found", ""}:
        return ""
    return cleaned


def _coerce_confidence(value: object) -> str:
    """Return a valid confidence label, defaulting to ``"none"``.

    The model is instructed to emit only ``high``/``medium``/``low``/
    ``none`` but lower tiers occasionally invent labels like
    ``"maybe"`` or ``"unknown"``. Any value outside the allowed set
    coerces to ``"none"`` so the caller's confidence-keyed logic stays
    well-defined.
    """
    if not isinstance(value, str):
        return "none"
    cleaned = value.strip().lower()
    if cleaned not in _VALID_CONFIDENCES:
        return "none"
    return cleaned


def _looks_like_email(s: str) -> bool:
    """Return ``True`` when ``s`` has the basic shape of an email.

    Cheap structural check -- ``"@"`` separator and a dot somewhere in
    the domain part. Real validation is the caller's responsibility
    (SMTP verify, MX check). This guard exists to reject obvious
    garbage like ``"see contact page"`` that occasionally slips
    through despite the prompt rules.
    """
    if "@" not in s:
        return False
    local, _, domain = s.partition("@")
    if not local or not domain:
        return False
    return "." in domain
