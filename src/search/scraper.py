import re
import aiohttp
from dataclasses import dataclass, field
from bs4 import BeautifulSoup

from src.utils.logger import get_logger

_logger = get_logger("scraper")

_TIMEOUT = aiohttp.ClientTimeout(total=15)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_STRIP_TAGS = {"nav", "footer", "header", "script", "style", "noscript", "aside"}


@dataclass
class ScrapeResult:
    content: str
    source_url: str
    is_primary: bool   # True if main site worked
    partial: bool      # True if some sources failed


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class WebScraper:
    async def scrape_to_markdown(self, url: str) -> str | None:
        """Scrape URL, return content as markdown. None on failure."""
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=_TIMEOUT, allow_redirects=True) as resp:
                    if resp.status in (403, 404):
                        _logger.warning("scraper: %d for %s", resp.status, url)
                        return None
                    if resp.status != 200:
                        _logger.warning("scraper: HTTP %d for %s", resp.status, url)
                        return None
                    html = await resp.text()
            return _html_to_text(html)
        except aiohttp.ServerTimeoutError:
            _logger.warning("scraper: timeout for %s", url)
            return None
        except aiohttp.ClientConnectionError:
            _logger.warning("scraper: connection refused for %s", url)
            return None
        except aiohttp.ClientError as exc:
            _logger.warning("scraper: client error for %s: %s", url, exc)
            return None

    async def scrape_with_fallback(
        self,
        company_name: str,
        primary_url: str,
        search_client=None,
    ) -> ScrapeResult:
        """Try primary URL first, search-based fallback if fails."""
        primary_content = await self.scrape_to_markdown(primary_url)

        if primary_content:
            _logger.info("scraper: primary site succeeded for %s", company_name)
            return ScrapeResult(
                content=primary_content,
                source_url=primary_url,
                is_primary=True,
                partial=False,
            )

        _logger.info("scraper: primary site failed for %s, trying fallback", company_name)

        if search_client is None:
            return ScrapeResult(
                content="",
                source_url=primary_url,
                is_primary=False,
                partial=True,
            )

        # Fallback: search for the company and scrape top 3 results
        try:
            results = await search_client.search(company_name, num_results=3)
        except Exception as exc:
            _logger.error("scraper: search fallback failed for %s: %s", company_name, exc)
            results = []

        collected_parts: list[str] = []
        any_failed = False

        for result in results[:3]:
            content = await self.scrape_to_markdown(result.url)
            if content:
                collected_parts.append(f"Source: {result.url}\n\n{content}")
            else:
                any_failed = True

        combined = "\n\n---\n\n".join(collected_parts) if collected_parts else ""

        fallback_url = results[0].url if results else primary_url

        _logger.info(
            "scraper: fallback gathered %d sources for %s (partial=%s)",
            len(collected_parts),
            company_name,
            any_failed or not collected_parts,
        )

        return ScrapeResult(
            content=combined,
            source_url=fallback_url,
            is_primary=False,
            partial=any_failed or not collected_parts,
        )
