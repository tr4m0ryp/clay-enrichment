"""
Brand website resolver.

Given a company name (and optionally a suspect URL from discovery),
finds the brand's actual root website by running a SearXNG query and
filtering results by:
  1. Known aggregator/reseller/social blacklist
  2. Name-match heuristic: prefer hostnames that contain a normalized
     form of the company name

This fixes the enrichment bottleneck where discovery extracted companies
from Reddit/listicle threads and either left Website empty or assigned
the listicle URL itself.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from src.utils.logger import get_logger

_logger = get_logger("website_resolver")

# Hostnames that are never a brand's own website. Match either exact
# hostname or any subdomain (e.g. "www.facebook.com", "m.facebook.com").
_AGGREGATOR_HOSTS: set[str] = {
    # Social
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "tiktok.com", "pinterest.com", "youtube.com", "linkedin.com",
    "snapchat.com", "threads.net",
    # Wikis / reference / forums
    "wikipedia.org", "wikiwand.com", "reddit.com", "quora.com",
    "medium.com", "substack.com",
    # Fashion resellers / marketplaces
    "ssense.com", "farfetch.com", "matchesfashion.com", "net-a-porter.com",
    "mrporter.com", "asos.com", "zalando.com", "zalando.co.uk",
    "zalando.de", "zalando.nl", "nordstrom.com", "amazon.com",
    "amazon.co.uk", "amazon.de", "amazon.nl", "amazon.fr", "amazon.es",
    "amazon.it", "ebay.com", "ebay.co.uk", "ebay.de", "etsy.com",
    "aboutyou.com", "aboutyou.de", "breuninger.com", "mytheresa.com",
    "lyst.com", "lyst.co.uk", "lyst.fr", "lyst.de", "ssense.ca",
    "revolve.com", "shopbop.com", "endclothing.com", "hbx.com",
    "selfridges.com", "harrods.com", "liberty.co.uk", "bloomingdales.com",
    "saks.com", "neimanmarcus.com",
    # Aggregator / review / directory / B-corp lookups
    "goodonyou.eco", "crunchbase.com", "tracxn.com", "yelp.com",
    "glassdoor.com", "indeed.com", "trustpilot.com", "scam-detector.com",
    "bcorporation.net", "usca.bcorporation.net", "calgarydirect.ca",
    "pitchbook.com", "owler.com", "zoominfo.com", "apollo.io",
    "rocketreach.co", "dnb.com",
    # AI / chat services that sometimes surface as noise
    "claude.ai", "chatgpt.com", "openai.com",
    # Known listicle sites seen in prior discovery runs
    "backwardfashion.com", "theperfumeshop.com", "select-mode-online.de",
    "atelier957.com", "discobrands.co", "fierceemphasis.com",
    "apartstyle.com",
}

# URL path substrings that indicate editorial/listicle content even on
# legitimate domains (e.g. a brand's own blog is fine, but SSENSE editorial
# is not -- ssense.com is already in the blacklist so this is extra safety).
_ARTICLE_PATH_HINTS: tuple[str, ...] = (
    "/editorial/", "/article/", "/articles/", "/blog/", "/news/",
    "/r/", "/search/", "/list-", "/best-", "/top-", "/guide/",
    "/review/", "/reviews/",
)


def _normalize_name(name: str) -> str:
    """Collapse a company name to a lowercase alpha-numeric token.

    Examples:
        "Never Fully Dressed" -> "neverfullydressed"
        "A.P.C." -> "apc"
        "Chloé" -> "chloe"
        "Filling Pieces" -> "fillingpieces"
    """
    # Transliterate common accented characters
    table = str.maketrans(
        "áàâäãåéèêëíìîïóòôöõúùûüñçÁÀÂÄÃÅÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇ",
        "aaaaaaeeeeiiiiooooouuuuncAAAAAAEEEEIIIIOOOOOUUUUNC",
    )
    cleaned = name.translate(table).lower()
    return re.sub(r"[^a-z0-9]", "", cleaned)


def _hostname(url: str) -> str:
    """Return lowercased hostname with leading 'www.' stripped."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_aggregator(url: str) -> bool:
    """True if the URL hostname is on the blacklist, or path looks like a listicle."""
    host = _hostname(url)
    if not host:
        return True
    # Exact or suffix match (subdomain of a blacklisted host)
    for bad in _AGGREGATOR_HOSTS:
        if host == bad or host.endswith("." + bad):
            return True
    path = urlparse(url).path.lower()
    for hint in _ARTICLE_PATH_HINTS:
        if hint in path:
            return True
    return False


def _root_url(url: str) -> str:
    """Return scheme://host (strip path). Falls back to the input on parse errors."""
    try:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except ValueError:
        pass
    return url


_MULTI_LABEL_TLDS: set[str] = {
    "co.uk", "co.jp", "co.nz", "co.za", "com.au", "com.br",
    "com.cn", "com.mx", "com.tr",
}


def _main_label(host: str) -> str:
    """Return the registrable main label of a hostname (second-to-last for
    single-label TLDs; third-to-last for known multi-label TLDs like co.uk).

    Examples:
        "shop.chloe.com"     -> "chloe"
        "rundholz.shop"      -> "rundholz"
        "brand.co.uk"        -> "brand"
        "poppy-barley.calgarydirect.ca" -> "calgarydirect"
    """
    parts = host.split(".")
    if len(parts) < 2:
        return host
    tail_two = ".".join(parts[-2:])
    if tail_two in _MULTI_LABEL_TLDS and len(parts) >= 3:
        return parts[-3]
    return parts[-2]


def _name_matches_host(norm_name: str, host: str) -> bool:
    """True if the normalized company name is contained in the host's main label.

    Matches against the registrable main label only (e.g. 'chloe' in
    'chloe.com', 'rundholz' in 'rundholz.shop') -- not against subdomains,
    which would let directory sites like 'poppy-barley.calgarydirect.ca'
    slip through.
    """
    if not norm_name or not host:
        return False
    label = _main_label(host).replace("-", "").replace(".", "").lower()
    return norm_name in label


async def resolve_website(
    company_name: str,
    search_client,
    existing_url: str = "",
) -> str:
    """Return a likely real brand website URL, or empty string if unresolvable.

    Logic:
      1. If existing_url is non-empty and not an aggregator AND its hostname
         matches the company name, keep it.
      2. Otherwise query SearXNG for `"{company_name}" official site` and
         pick the first result whose hostname is not an aggregator AND
         contains a normalized form of the company name.
      3. Fall back to the first non-aggregator result if no name-match is
         found (covers brands with very different domains, e.g. "A.P.C."
         -> "apcstore.com").
      4. Return empty string if every result is an aggregator.

    The returned URL is the root (scheme://host) so enrichment can scrape
    the homepage consistently regardless of which deep-link the search
    happened to surface.
    """
    norm = _normalize_name(company_name)

    # Step 1: keep a clean existing URL that matches the brand name
    if existing_url:
        host = _hostname(existing_url)
        if host and not _is_aggregator(existing_url) and _name_matches_host(norm, host):
            return _root_url(existing_url)

    # Step 2: search for the brand
    query = f'"{company_name}" official site'
    try:
        results = await search_client.search(query, num_results=10)
    except Exception as exc:
        _logger.warning("resolver: search failed for '%s': %s", company_name, exc)
        return _root_url(existing_url) if existing_url and not _is_aggregator(existing_url) else ""

    if not results:
        _logger.info("resolver: no results for '%s'", company_name)
        return ""

    # Step 3: prefer name-matching hostnames
    first_clean: str = ""
    for r in results:
        if _is_aggregator(r.url):
            continue
        host = _hostname(r.url)
        if not host:
            continue
        if not first_clean:
            first_clean = _root_url(r.url)
        if _name_matches_host(norm, host):
            resolved = _root_url(r.url)
            _logger.info("resolver: '%s' -> %s (name match)", company_name, resolved)
            return resolved

    # Step 4: fall back to first non-aggregator
    if first_clean:
        _logger.info("resolver: '%s' -> %s (first clean)", company_name, first_clean)
        return first_clean

    _logger.info("resolver: '%s' -> no clean result found", company_name)
    return ""
