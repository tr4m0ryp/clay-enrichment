"""Public surface for the GitHub Gemini-key scraper package.

Callers should import the two coroutines below, never reach into the
private submodules. The scraper hits GitHub Code Search through a
rotating PAT pool, fetches matching raw files, regex-extracts candidate
Gemini keys, dedupes them, and (optionally) stores plus inline-validates
the survivors.
"""

from src.api_keys.scraper.orchestrator import (
    scrape_all_sources,
    scrape_github_keys,
)


__all__ = [
    "scrape_github_keys",
    "scrape_all_sources",
]
