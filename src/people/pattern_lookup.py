"""Hunter Domain Search wrapper with Postgres-backed cache.

One Hunter credit unlocks the email pattern for an entire domain. Pattern
is cached forever in companies.email_pattern; subsequent contacts at the
same company use the cached pattern with no further API call.

Per research F14: Hunter free tier is 50 credits/month, permanent. If
the free tier is exhausted (HTTP 429 or non-200), the lookup returns
("", "none") and the caller falls through to the Gemini-grounded
published-email path.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import aiohttp

from src.config import Config
from src.db.companies import CompaniesDB

logger = logging.getLogger(__name__)

HUNTER_DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"
HUNTER_EMAIL_FINDER_URL = "https://api.hunter.io/v2/email-finder"
TIMEOUT_SECONDS = 15.0
# Hunter Email Finder returns a confidence score 0-100. We treat scores
# below this as "Hunter doesn't really know the address" and fall back
# to deterministic pattern construction.
EMAIL_FINDER_MIN_SCORE = 60


class PatternLookup:
    """Cache-first pattern detector. Hits Hunter at most once per company."""

    def __init__(self, config: Config, companies_db: CompaniesDB) -> None:
        self._api_key = (config.hunter_api_key or "").strip()
        self._companies_db = companies_db

    async def get_pattern(
        self, company_id: str, domain: str
    ) -> tuple[str, str]:
        """Return (pattern, source) for the company's email format.

        Source values:
          - 'hunter' -- fresh result from Hunter Domain Search
          - 'cache'  -- previously stored pattern read from companies row
          - 'none'   -- no pattern available (empty config, no domain,
                        Hunter rate-limited, or Hunter returned nothing).

        Pattern is the literal Hunter template, e.g. '{first}.{last}',
        '{f}{last}', '{first}'. Empty string when no pattern.
        """
        if not domain:
            return "", "none"

        # Cache check via direct SQL since CompaniesDB has no find_by_id.
        cached_row = await self._read_cache(company_id)
        if cached_row is not None:
            cached = (cached_row.get("email_pattern") or "").strip()
            cached_src = (cached_row.get("email_pattern_source") or "").strip()
            if cached:
                return cached, "cache"
            if cached_src == "none":
                # Negative cache -- already tried, came up empty.
                return "", "none"

        if not self._api_key:
            logger.info(
                "PatternLookup: no HUNTER_API_KEY configured, skipping %s",
                domain,
            )
            await self._write_cache(company_id, "", "none")
            return "", "none"

        logger.info("PatternLookup: cache miss for %s, calling Hunter", domain)
        pattern = await self._call_hunter(domain)
        source = "hunter" if pattern else "none"
        await self._write_cache(company_id, pattern, source)
        return pattern, source

    async def _read_cache(self, company_id: str) -> dict | None:
        """Fetch the cached email_pattern columns for a company."""
        try:
            cid = UUID(company_id)
        except (ValueError, TypeError):
            logger.warning(
                "PatternLookup: invalid company_id %r, skipping cache read",
                company_id,
            )
            return None
        row = await self._companies_db._pool.fetchrow(
            "SELECT email_pattern, email_pattern_source "
            "FROM companies WHERE id = $1",
            cid,
        )
        return dict(row) if row else None

    async def _call_hunter(self, domain: str) -> str:
        """Single Hunter Domain Search call. Returns pattern or empty string."""
        # Auth via Authorization header rather than ?api_key= URL param --
        # keys in URLs leak to access logs / proxies / browser history.
        # Hunter has supported Bearer auth for years.
        params = {"domain": domain}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    HUNTER_DOMAIN_SEARCH_URL, params=params, headers=headers,
                ) as resp:
                    body = await self._safe_json(resp)
                    if resp.status == 429:
                        logger.warning(
                            "PatternLookup: Hunter rate-limited for %s",
                            domain,
                        )
                        return ""
                    if resp.status != 200:
                        logger.warning(
                            "PatternLookup: Hunter %s for %s: %s",
                            resp.status, domain, str(body)[:200],
                        )
                        return ""
                    data = (body or {}).get("data") or {}
                    pattern = (data.get("pattern") or "").strip()
                    if pattern:
                        logger.info(
                            "PatternLookup: %s -> %s", domain, pattern,
                        )
                    else:
                        logger.info(
                            "PatternLookup: no pattern returned for %s",
                            domain,
                        )
                    return pattern
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning(
                "PatternLookup: HTTP error for %s: %s", domain, exc,
            )
            return ""

    @staticmethod
    async def _safe_json(resp: aiohttp.ClientResponse) -> dict | None:
        """Decode JSON without raising on bad content-type or empty body."""
        try:
            return await resp.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            return None

    async def _write_cache(
        self, company_id: str, pattern: str, source: str,
    ) -> None:
        """Persist pattern + source on the companies row."""
        try:
            await self._companies_db.update_company(
                company_id,
                {"email_pattern": pattern, "email_pattern_source": source},
            )
        except Exception:
            logger.exception(
                "PatternLookup: failed to write pattern cache for %s",
                company_id,
            )

    async def find_email(
        self, domain: str, first: str, last: str,
    ) -> tuple[str, int, str]:
        """Hunter Email Finder lookup -- returns (email, score, linkedin_url).

        Better accuracy than pattern construction because Hunter returns
        the actual address its crawler has indexed (or, when not indexed,
        Hunter's own best-guess construction with a calibrated score).
        Hunter's response also exposes a verified ``linkedin`` field
        whenever its crawler associated a LinkedIn slug with the contact
        -- captured here so the resolver can populate
        ``contacts.linkedin_url`` from a real, indexable source instead
        of leaving it empty (the prompt-only path produced dead links).

        Costs 1 Hunter credit per call -- intended for high-priority
        leads only (called from the email_resolver worker after scoring).
        Returns ("", 0, "") when:
          - api_key is unset
          - first or domain is empty
          - Hunter returns nothing or non-200
          - the returned confidence score is below EMAIL_FINDER_MIN_SCORE
            (caller should fall back to deterministic construction;
            linkedin_url is still returned in this case if Hunter
            supplied one, since it is independent of email confidence)
        """
        if not self._api_key or not domain or not first:
            return "", 0, ""
        params = {
            "domain": domain,
            "first_name": first,
            "last_name": last or "",
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    HUNTER_EMAIL_FINDER_URL, params=params, headers=headers,
                ) as resp:
                    body = await self._safe_json(resp) or {}
                    if resp.status == 429:
                        logger.warning(
                            "Hunter Email Finder rate-limited for %s %s @ %s",
                            first, last, domain,
                        )
                        return "", 0, ""
                    if resp.status != 200:
                        logger.warning(
                            "Hunter Email Finder %s for %s %s @ %s: %s",
                            resp.status, first, last, domain,
                            str(body)[:200],
                        )
                        return "", 0, ""
                    data = (body or {}).get("data") or {}
                    email = (data.get("email") or "").strip()
                    score = int(data.get("score") or 0)
                    linkedin_url = _normalize_linkedin(data.get("linkedin"))
                    logger.info(
                        "Hunter Email Finder: %s %s @ %s -> %s "
                        "(score=%d, linkedin=%s)",
                        first, last, domain, email or "(none)",
                        score, linkedin_url or "(none)",
                    )
                    if email and score >= EMAIL_FINDER_MIN_SCORE:
                        return email, score, linkedin_url
                    return "", score, linkedin_url
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning(
                "Hunter Email Finder HTTP error for %s @ %s: %s",
                first, domain, exc,
            )
            return "", 0, ""


def _normalize_linkedin(value: object) -> str:
    """Coerce Hunter's ``linkedin`` field into a canonical absolute URL.

    Hunter returns one of three shapes for that field:
      - a full URL  ``https://www.linkedin.com/in/<slug>``
      - a bare slug ``<slug>``         (we prepend the canonical prefix)
      - ``None`` / empty string        (return ``""``)

    Anything that doesn't look LinkedIn-shaped after normalization is
    rejected so a stray bad value can't pollute the dashboard's
    clickable link.
    """
    if not isinstance(value, str):
        return ""
    s = value.strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        if "linkedin.com" not in s.lower():
            return ""
        return s
    # bare slug -- accept letters/digits/-/./_ as LinkedIn allows
    if any(ch in s for ch in (" ", "/", "?", "#")):
        return ""
    return f"https://www.linkedin.com/in/{s}"


def construct_email(
    pattern: str, first: str, last: str, domain: str,
) -> str:
    """Build an email from Hunter's pattern + name + domain.

    Substitutes Hunter placeholders: {first}, {last}, {f}, {l},
    {first_initial}, {last_initial}. Lowercases everything; strips
    non-ASCII letters and whitespace from name parts.

    Returns empty string when:
      - pattern is empty
      - domain is empty
      - both first and last normalize to empty
      - the pattern contains an unhandled placeholder (a stray '{')
      - the resulting local-part is empty
    """
    if not pattern or not domain:
        return ""

    f = _normalize_name(first)
    l = _normalize_name(last)
    if not f and not l:
        return ""

    fi = f[:1] if f else ""
    li = l[:1] if l else ""

    local = (
        pattern
        .replace("{first}", f)
        .replace("{last}", l)
        .replace("{first_initial}", fi)
        .replace("{last_initial}", li)
        .replace("{f}", fi)
        .replace("{l}", li)
    )
    if "{" in local or not local:
        logger.warning(
            "construct_email: unhandled placeholder in pattern %r", pattern,
        )
        return ""
    return f"{local}@{domain}"


def _normalize_name(part: str) -> str:
    """Lowercase + transliterate accented chars + keep ASCII letters only.

    Uses NFKD decomposition to strip combining marks so common
    international characters are mapped to their ASCII counterparts:
    "á" -> "a", "ñ" -> "n", "Ø" -> "o". Hyphens, periods, apostrophes,
    and other punctuation are dropped -- email local-parts conventionally
    don't include them.

    Examples:
        "Álvarez-Ossorio" -> "alvarezossorio"
        "Iñigo"           -> "inigo"
        "Møller"          -> "moller"
        "O'Brien"         -> "obrien"
    """
    import unicodedata
    if not part:
        return ""
    # Pre-translate characters that NFKD doesn't decompose (precomposed
    # codepoints with no combining-mark equivalent: Nordic ø/æ/å, German
    # ß, Polish ł, Icelandic þ/ð, etc.).
    pretranslate = {
        "ø": "o", "Ø": "o",   # ø, Ø
        "æ": "ae", "Æ": "ae", # æ, Æ
        "å": "a", "Å": "a",   # å, Å
        "ß": "ss",                 # ß
        "ł": "l", "Ł": "l",   # ł, Ł
        "ð": "d", "Ð": "d",   # ð, Ð
        "þ": "th", "Þ": "th", # þ, Þ
    }
    pre = "".join(pretranslate.get(ch, ch) for ch in part)
    folded = pre.casefold().strip()
    decomposed = unicodedata.normalize("NFKD", folded)
    ascii_only = decomposed.encode("ascii", errors="ignore").decode("ascii")
    return "".join(ch for ch in ascii_only if "a" <= ch <= "z")


def _legacy_normalize_name_unused(part: str) -> str:
    """(deprecated -- replaced by _normalize_name above)."""
    if not part:
        return ""
    out = []
    for ch in part.lower().strip():
        if "a" <= ch <= "z":
            out.append(ch)
    return "".join(out)
