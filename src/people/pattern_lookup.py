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
TIMEOUT_SECONDS = 15.0


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
        params = {"domain": domain, "api_key": self._api_key}
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    HUNTER_DOMAIN_SEARCH_URL, params=params
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
