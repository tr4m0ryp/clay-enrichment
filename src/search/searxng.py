"""
SearXNG meta-search client.

Queries a self-hosted SearXNG instance which aggregates results from
Google, Bing, DuckDuckGo, Brave, and other search engines. Free,
unlimited, no API keys needed.

Requires a running SearXNG instance (Docker recommended):
    docker run -d -p 8888:8080 searxng/searxng
"""

import ssl
import aiohttp
import certifi
from dataclasses import dataclass

from src.utils.logger import get_logger

_logger = get_logger("searxng")


@dataclass
class SearchResult:
    """A single search result from SearXNG."""
    title: str
    url: str
    snippet: str


class SearXNGClient:
    """
    Async client for a self-hosted SearXNG instance.

    SearXNG is a meta-search engine that queries multiple search engines
    simultaneously and returns combined, deduplicated results. No API
    keys required.
    """

    def __init__(self, base_url: str = "http://localhost:8888") -> None:
        """
        Initialize the SearXNG client.

        Args:
            base_url: URL of the SearXNG instance (default: localhost:8888).
        """
        self._base_url = base_url.rstrip("/")
        self._search_url = f"{self._base_url}/search"

    async def search(self, query: str, num_results: int = 10) -> list[SearchResult]:
        """
        Execute a search query via SearXNG.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return.

        Returns:
            List of SearchResult objects.
        """
        _logger.info("searxng: query=%r num=%d", query, num_results)

        params = {
            "q": query,
            "format": "json",
            "categories": "general",
            "language": "en",
            "pageno": 1,
        }

        try:
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    self._search_url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        _logger.warning(
                            "searxng: HTTP %d for query=%r", resp.status, query
                        )
                        return []
                    data = await resp.json()
        except aiohttp.ClientError as exc:
            _logger.error("searxng: request failed: %s", exc)
            return []

        raw_results = data.get("results", [])
        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
            for item in raw_results[:num_results]
        ]

        _logger.info(
            "searxng: got %d results for query=%r (engines: %s)",
            len(results),
            query,
            ", ".join(data.get("engines", [])),
        )
        return results

    async def search_site(
        self, query: str, site: str, num_results: int = 10
    ) -> list[SearchResult]:
        """
        Search within a specific site.

        Args:
            query: The search query string.
            site: Domain to restrict search to (e.g., linkedin.com/in).
            num_results: Maximum number of results.

        Returns:
            List of SearchResult objects from the specified site.
        """
        site_query = f"site:{site} {query}"
        return await self.search(site_query, num_results=num_results)

    async def is_available(self) -> bool:
        """
        Check if the SearXNG instance is reachable.

        Returns:
            True if the instance responds, False otherwise.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self._base_url,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except aiohttp.ClientError:
            return False
