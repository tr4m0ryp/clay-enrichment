"""Gemini-grounded fallback finder for Prospeo NO_MATCH contacts.

When Prospeo's database doesn't have a contact (typical for niche EU
brands), this module runs a single grounded Gemini call to mine the
open web for the contact's LinkedIn URL and most likely work email.
Sources include team pages, conference speaker bios, press releases,
podcast guests -- everywhere Prospeo's crawler doesn't reach.

The email guess is *not* trusted blindly: it goes through MyEmailVerifier
downstream, exactly like Prospeo's and Hunter's outputs. Only verified
addresses are persisted. LinkedIn URLs are validated structurally
before being kept.

Each call (hit or miss) is logged to ``gemini_finder_usage`` so the
dashboard can show "tried by Gemini" stats and the email_resolver can
skip contacts already attempted in the past 7 days.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import asyncpg

from src.gemini.client import GeminiClient
from src.prompts.base_context import build_system_prompt
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)

# Skip if Gemini was already tried for this contact in the last 7 days.
# Same person, same company, same web pages -- a re-run is unlikely to
# surface different data and burns paid Gemini grounded-search quota.
_RETRY_COOLDOWN_DAYS = 7

PROMPT = build_system_prompt("""\
## Task
Find BOTH the LinkedIn profile URL AND the most likely work email for
a specific person at a specific company. You have Google Search
grounding enabled -- use it. The downstream pipeline NEEDS BOTH
fields. Returning only one when the other is findable is the most
common failure mode. Do not commit it.

## Inputs
- {contact_name}: full name (string)
- {job_title}: current job title (string, may be empty)
- {company_name}: employer (string)
- {company_website}: employer's website URL (string)
- {context}: free-text context about the person from prior research
  (string, may be empty)

## Procedure -- follow these steps in order, do not skip any
1. Run a LinkedIn-targeted search: ``"{contact_name}" "{company_name}" site:linkedin.com/in``
   Inspect the top 5 results. The correct profile slug typically
   matches the contact's name (linkedin.com/in/<firstname-lastname>
   or a similar variant). Confirm the profile mentions
   {company_name} or a closely related company in the headline /
   experience snippet. Capture the URL.
2. Run a published-email search: ``"{contact_name}" "@{company_website}"``
   plus a second pass for ``"{contact_name}" {company_name} contact``.
   Inspect company team pages, press releases, conference speaker
   bios, podcast guest pages. Capture any email at
   {company_website}'s domain.
3. If step 2 yielded nothing, run a peer-pattern search: ``"@{company_website}"``
   to find any 2-3 example employee emails. Infer the company-wide
   pattern (firstname.lastname@, firstname@, firstinitial+lastname@,
   etc) and apply it to {contact_name}. Mark email_confidence="medium".
4. Only AFTER steps 1-3 are completed, build the JSON output.

If step 1 found nothing, retry it with a relaxed query (drop the
quotes, swap the company name for the domain). If step 2 found
nothing, retry with the contact's first name only.

Returning a non-empty email with an empty linkedin_url means you did
not run step 1 properly. Returning a non-empty linkedin_url with an
empty email means you did not run steps 2-3 properly. The prior
output that's been failing in production looks exactly like that --
do not repeat it.

## Output Format -- EXACT
Return ONLY a valid JSON object. No markdown fences, no prose.

{
  "linkedin_url": "string -- full LinkedIn profile URL or empty string",
  "email": "string -- work email at the company's domain or empty string",
  "email_confidence": "string -- one of: high, medium, low, none",
  "linkedin_confidence": "string -- one of: high, medium, low, none",
  "sources": ["string -- absolute URL the answer was derived from"]
}

### Field rules
- linkedin_url: a real, current LinkedIn profile URL you can verify in
  the search results. Format: ``https://www.linkedin.com/in/<slug>``.
  Empty string when not findable -- do NOT fabricate slugs.
- email: must end with @ + the company's primary domain. Off-domain
  matches (personal Gmail, vendor emails, contact@) are rejected by
  the caller. Empty string when no candidate email is visible AND no
  pattern is inferable from peers at the same company.
- email_confidence: high when literally published on a primary source
  (team page, press release); medium when inferred from a clear
  company-wide pattern visible in 2+ peer emails; low when guessed
  from a single sample; none when no signal.
- linkedin_confidence: high when a search result page links directly
  to the profile and the slug matches the name+company; medium when
  the profile is found but the company page hasn't been verified;
  low when only the slug shape suggests it; none when not found.
- sources: list of URLs you actually used (LinkedIn search result
  pages, team pages, press releases). 2-5 entries typically.

## Hard Rules
- Output is JSON ONLY.
- BOTH searches must be attempted. Returning a result with one field
  empty when you didn't even try the search for it is a failure.
- Never fabricate URLs.
- Never use sentinel strings ("Unknown", "N/A", etc).
- Never use emojis.
- Never include keys not in the schema.
""")


# Targeted follow-up prompts. Used when the primary call returned
# only one of the two fields -- a single focused search has higher
# recall than re-running the combined prompt.

PROMPT_LINKEDIN_ONLY = build_system_prompt("""\
## Task
Find ONLY the LinkedIn profile URL for the named contact. The
caller already has the work email; they need the LinkedIn URL.

## Inputs
- {contact_name}: full name
- {job_title}: current job title (may be empty)
- {company_name}: employer
- {company_website}: employer's website URL

## Procedure
1. Run: ``"{contact_name}" "{company_name}" site:linkedin.com/in``
2. If no exact match in top results, retry without quotes.
3. If still nothing, run: ``{contact_name} {company_name} linkedin``
   and inspect any linkedin.com/in/* result.
4. Confirm the profile's headline / experience mentions
   {company_name} or a closely related company before accepting.

## Output -- EXACT JSON, nothing else
{
  "linkedin_url": "string -- https://www.linkedin.com/in/<slug> or empty",
  "linkedin_confidence": "high | medium | low | none",
  "sources": ["string -- absolute URL"]
}

Empty string is preferred over a fabricated slug. Never invent.
""")

PROMPT_EMAIL_ONLY = build_system_prompt("""\
## Task
Find ONLY the work email for the named contact at {company_website}.
The caller already has the LinkedIn URL; they need the email.

## Inputs
- {contact_name}: full name
- {job_title}: current job title (may be empty)
- {company_name}: employer
- {company_website}: employer's website URL

## Procedure
1. Run: ``"{contact_name}" "@{company_website}"``
2. Run: ``{contact_name} {company_name} contact email``
3. If neither yielded a published email, run ``"@{company_website}"``
   to find 2-3 peer emails. Infer the pattern
   (firstname.lastname@, firstname@, etc) and apply it.

## Output -- EXACT JSON, nothing else
{
  "email": "string -- email at @{company_website} or empty",
  "email_confidence": "high | medium | low | none",
  "sources": ["string -- absolute URL"]
}

Email MUST end with @ + the company's primary domain. Off-domain
matches must be rejected. Empty string is preferred over a guess
without basis.
""")


_LINKEDIN_RE = re.compile(
    r"^https?://(?:[a-zA-Z]{2,5}\.)?linkedin\.com/in/[A-Za-z0-9._\-%]+/?$"
)
_VALID_CONFIDENCES = frozenset({"high", "medium", "low", "none"})


def _normalize_linkedin_url(raw: str) -> str:
    """Return a canonical LinkedIn profile URL or empty string on reject.

    Gemini's grounded responses sometimes return URLs with query
    params (?utm_source=...), trailing whitespace, or capitalized
    subdomains -- all of which the bare regex would reject. Strip
    those before validation so a real URL doesn't get dropped.
    """
    if not raw:
        return ""
    s = raw.strip()
    # Drop fragment + query so utm tracking junk doesn't break the regex
    for sep in ("?", "#"):
        if sep in s:
            s = s.split(sep, 1)[0]
    s = s.rstrip("/")
    # Reject if the domain isn't linkedin.com/in -- catches cases where
    # Gemini returned a company page (linkedin.com/company/...) or a
    # search results URL.
    if "linkedin.com/in/" not in s.lower():
        return ""
    if not _LINKEDIN_RE.match(s + "/"):
        return ""
    return s


@dataclass
class GeminiFinderResult:
    """Fields the email_resolver consumes from a successful call."""

    email: str = ""
    email_confidence: str = "none"
    linkedin_url: str = ""
    linkedin_confidence: str = "none"
    sources: list[str] | None = None
    raw: dict | None = None


class GeminiGroundedFinder:
    """Single grounded Gemini call per (Prospeo NO_MATCH) contact.

    Backed by the existing GeminiClient pool, so it inherits the
    private Tier-1 fallback when harvested keys are exhausted. Logs
    every call to ``gemini_finder_usage`` for dashboard accounting.
    """

    def __init__(
        self,
        gemini_client: GeminiClient,
        usage_pool: asyncpg.Pool | None = None,
    ):
        self._gemini = gemini_client
        self._usage_pool = usage_pool
        logger.info(
            "GeminiGroundedFinder ready (usage_logging=%s)",
            "on" if usage_pool is not None else "off",
        )

    @property
    def enabled(self) -> bool:
        return self._gemini is not None

    async def already_tried_recently(self, contact_id: str | None) -> bool:
        """Return True when we've already called Gemini for this contact
        within the cooldown window. Skips paid grounded calls on
        contacts that already returned nothing.
        """
        if not contact_id or self._usage_pool is None:
            return False
        try:
            async with self._usage_pool.acquire() as conn:
                row = await conn.fetchval(
                    """
                    SELECT 1 FROM gemini_finder_usage
                    WHERE contact_id = $1::uuid
                      AND used_at >= now() - ($2::int * interval '1 day')
                    LIMIT 1
                    """,
                    contact_id, _RETRY_COOLDOWN_DAYS,
                )
            return row is not None
        except Exception:
            logger.warning(
                "GeminiGroundedFinder: cooldown probe failed; allowing call",
                exc_info=True,
            )
            return False

    async def find(
        self,
        contact_id: str | None,
        contact_name: str,
        job_title: str,
        company_name: str,
        company_website: str,
        domain: str,
        context: str,
    ) -> GeminiFinderResult | None:
        """Resolve one contact. Returns None on any failure mode --
        empty inputs, parse error, all-empty fields, off-domain email,
        or LinkedIn URL that doesn't structurally validate.
        """
        if not contact_name or not domain:
            return None

        rendered = (
            PROMPT
            .replace("{contact_name}", contact_name)
            .replace("{job_title}", job_title or "")
            .replace("{company_name}", company_name or domain)
            .replace("{company_website}", company_website or domain)
            .replace("{context}", (context or "")[:1500])
        )

        async def _call(user_message: str) -> dict:
            return await self._gemini.generate(
                prompt=rendered,
                user_message=user_message,
                grounding=True,
                json_mode=True,
                max_retries=10,
            )

        base_msg = (
            f"Find the LinkedIn URL and work email for "
            f"{contact_name}, {job_title or 'unknown role'} "
            f"at {company_name or domain}."
        )

        result_tuple = None
        try:
            result_tuple = await retry_on_malformed_json(_call, base_msg)
        except Exception:
            logger.exception(
                "GeminiGroundedFinder: call failed for %s @ %s",
                contact_name, domain,
            )
            await self._log_usage(contact_id, domain, found_email=False,
                                  found_linkedin=False, error=True)
            return None

        if result_tuple is None:
            await self._log_usage(contact_id, domain, found_email=False,
                                  found_linkedin=False, error=True)
            return None

        parsed, _raw = result_tuple
        if not isinstance(parsed, dict):
            await self._log_usage(contact_id, domain, found_email=False,
                                  found_linkedin=False, error=True)
            return None

        out = self._extract(parsed, domain)

        # Targeted recovery: if the primary call returned only one of
        # the two fields, run a focused follow-up to fill the gap. The
        # follow-up prompts are narrower (single-field search procedure)
        # and recall the missing field much more reliably than the
        # combined prompt. Cost: 1 extra grounded call only on partial
        # hits, never on full hits or full misses.
        if out.email and not out.linkedin_url:
            logger.info(
                "GeminiGroundedFinder: partial (email-only) for %s @ %s "
                "-- running LinkedIn-only follow-up",
                contact_name, domain,
            )
            li = await self._followup_linkedin(
                contact_name, job_title, company_name or domain,
                company_website or domain,
            )
            if li:
                out.linkedin_url = li
        elif out.linkedin_url and not out.email:
            logger.info(
                "GeminiGroundedFinder: partial (linkedin-only) for %s @ %s "
                "-- running email-only follow-up",
                contact_name, domain,
            )
            em = await self._followup_email(
                contact_name, job_title, company_name or domain,
                company_website or domain, domain,
            )
            if em:
                out.email = em

        await self._log_usage(
            contact_id, domain,
            found_email=bool(out.email),
            found_linkedin=bool(out.linkedin_url),
            error=False,
        )
        if not out.email and not out.linkedin_url:
            return None
        logger.info(
            "GeminiGroundedFinder: hit for %s @ %s "
            "(email=%s linkedin=%s sources=%d)",
            contact_name, domain,
            out.email or "(none)",
            out.linkedin_url or "(none)",
            len(out.sources or []),
        )
        return out

    async def _followup_linkedin(
        self,
        contact_name: str,
        job_title: str,
        company_name: str,
        company_website: str,
    ) -> str:
        """One focused grounded call for just the LinkedIn URL. Returns
        a normalized URL or empty string. Failures are swallowed --
        partial result is preferable to crashing the whole resolution.
        """
        rendered = (
            PROMPT_LINKEDIN_ONLY
            .replace("{contact_name}", contact_name)
            .replace("{job_title}", job_title or "")
            .replace("{company_name}", company_name)
            .replace("{company_website}", company_website)
        )

        async def _call(user_message: str) -> dict:
            return await self._gemini.generate(
                prompt=rendered,
                user_message=user_message,
                grounding=True,
                json_mode=True,
                max_retries=5,
            )

        msg = f"Find LinkedIn URL for {contact_name} at {company_name}."
        try:
            result = await retry_on_malformed_json(_call, msg)
        except Exception:
            logger.warning(
                "GeminiGroundedFinder: linkedin follow-up failed for %s",
                contact_name, exc_info=True,
            )
            return ""
        if result is None:
            return ""
        parsed, _ = result
        if not isinstance(parsed, dict):
            return ""
        return _normalize_linkedin_url(parsed.get("linkedin_url") or "")

    async def _followup_email(
        self,
        contact_name: str,
        job_title: str,
        company_name: str,
        company_website: str,
        domain: str,
    ) -> str:
        """One focused grounded call for just the work email. Returns
        a domain-validated email or empty string.
        """
        rendered = (
            PROMPT_EMAIL_ONLY
            .replace("{contact_name}", contact_name)
            .replace("{job_title}", job_title or "")
            .replace("{company_name}", company_name)
            .replace("{company_website}", company_website)
        )

        async def _call(user_message: str) -> dict:
            return await self._gemini.generate(
                prompt=rendered,
                user_message=user_message,
                grounding=True,
                json_mode=True,
                max_retries=5,
            )

        msg = f"Find work email for {contact_name} at {company_name}."
        try:
            result = await retry_on_malformed_json(_call, msg)
        except Exception:
            logger.warning(
                "GeminiGroundedFinder: email follow-up failed for %s",
                contact_name, exc_info=True,
            )
            return ""
        if result is None:
            return ""
        parsed, _ = result
        if not isinstance(parsed, dict):
            return ""
        email = (parsed.get("email") or "").strip().lower()
        if "@" not in email:
            return ""
        local, _, edomain = email.partition("@")
        if not local or edomain != domain.lower():
            return ""
        return email

    @staticmethod
    def _extract(parsed: dict, domain: str) -> GeminiFinderResult:
        email = (parsed.get("email") or "").strip().lower()
        if email and "@" in email:
            local, _, edomain = email.partition("@")
            if not local or edomain != domain.lower():
                # Off-domain match -- reject so we don't persist
                # vendor / personal emails as "the work email".
                email = ""
        linkedin_url = _normalize_linkedin_url(
            parsed.get("linkedin_url") or "",
        )
        sources_raw = parsed.get("sources") or []
        sources = [
            s for s in sources_raw
            if isinstance(s, str) and s.startswith("http")
        ][:10]
        return GeminiFinderResult(
            email=email,
            email_confidence=_coerce_confidence(parsed.get("email_confidence")),
            linkedin_url=linkedin_url,
            linkedin_confidence=_coerce_confidence(
                parsed.get("linkedin_confidence")
            ),
            sources=sources,
            raw=parsed,
        )

    async def _log_usage(
        self,
        contact_id: str | None,
        domain: str,
        *,
        found_email: bool,
        found_linkedin: bool,
        error: bool,
    ) -> None:
        if self._usage_pool is None:
            return
        try:
            async with self._usage_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO gemini_finder_usage
                        (contact_id, domain, found_email,
                         found_linkedin, error)
                    VALUES ($1::uuid, $2, $3, $4, $5)
                    """,
                    contact_id, domain,
                    bool(found_email), bool(found_linkedin), bool(error),
                )
        except Exception:
            logger.exception(
                "GeminiGroundedFinder: failed to log usage row "
                "(non-fatal -- continuing)",
            )


def _coerce_confidence(value: object) -> str:
    if not isinstance(value, str):
        return "none"
    cleaned = value.strip().lower()
    return cleaned if cleaned in _VALID_CONFIDENCES else "none"
