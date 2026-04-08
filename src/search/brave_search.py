"""
Brave Search API client.

Authenticated API that doesn't get blocked like SearXNG on cloud IPs.
$5/1000 queries with 1000 free queries/month ($5 credit auto-applied).

Sign up at: https://brave.com/search/api/
"""

import ssl
import aiohttp
import certifi
from dataclasses import dataclass

from src.utils.logger import get_logger

_logger = get_logger("brave_search")

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    snippet: str


class BraveSearchClient:
    """
    Async client for the Brave Search API.

    Uses an authenticated API key so it doesn't get blocked like
    unauthenticated meta-search proxies on cloud IPs.
    """

    def __init__(self, api_key: str) -> None:
        """
        Initialize with a Brave Search API key.

        Args:
            api_key: Brave Search API subscription token.
        """
        self._api_key = api_key

    async def search(self, query: str, num_results: int = 10) -> list[SearchResult]:
        """
        Execute a search query via Brave Search API.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return (max 20).

        Returns:
            List of SearchResult objects.
        """
        _logger.info("brave_search: query=%r num=%d", query, num_results)

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }

        params = {
            "q": query,
            "count": min(num_results, 20),
        }

        try:
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    _BRAVE_SEARCH_URL,
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        _logger.warning(
                            "brave_search: HTTP %d for query=%r", resp.status, query
                        )
                        return []
                    data = await resp.json()
        except aiohttp.ClientError as exc:
            _logger.error("brave_search: request failed: %s", exc)
            return []

        web_results = data.get("web", {}).get("results", [])
        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
            )
            for item in web_results[:num_results]
        ]

        _logger.info("brave_search: got %d results for query=%r", len(results), query)
        return results

    async def search_site(
        self, query: str, site: str, num_results: int = 10
    ) -> list[SearchResult]:
        """
        Search within a specific site.

        Args:
            query: The search query string.
            site: Domain to restrict search to.
            num_results: Maximum number of results.

        Returns:
            List of SearchResult objects from the specified site.
        """
        site_query = f"site:{site} {query}"
        return await self.search(site_query, num_results=num_results)
