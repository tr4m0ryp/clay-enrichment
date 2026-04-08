import aiohttp
from dataclasses import dataclass

from src.config import Config
from src.utils.logger import get_logger
from src.utils.rate_limiter import RateLimiter

_logger = get_logger("google_search")

_GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class GoogleSearchClient:
    def __init__(self, config: Config, rate_limiter: RateLimiter) -> None:
        self._api_key = config.google_api_key
        self._cse_id = config.google_cse_id
        self._rate_limiter = rate_limiter

    async def search(self, query: str, num_results: int = 10) -> list[SearchResult]:
        """Google Custom Search JSON API v1 via aiohttp."""
        await self._rate_limiter.acquire("google-custom-search")
        _logger.info("google_search: query=%r num=%d", query, num_results)

        params = {
            "key": self._api_key,
            "cx": self._cse_id,
            "q": query,
            "num": min(num_results, 10),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(_GOOGLE_CSE_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        _logger.warning("google_search: HTTP %d for query=%r", resp.status, query)
                        return []
                    data = await resp.json()
        except aiohttp.ClientError as exc:
            _logger.error("google_search: request failed: %s", exc)
            return []

        items = data.get("items", [])
        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            )
            for item in items
        ]
        _logger.info("google_search: got %d results for query=%r", len(results), query)
        return results

    async def search_site(self, query: str, site: str, num_results: int = 10) -> list[SearchResult]:
        """Search within a specific site (prepends site: to query)."""
        site_query = f"site:{site} {query}"
        return await self.search(site_query, num_results=num_results)
