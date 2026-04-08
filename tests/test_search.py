import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.search.google_search import GoogleSearchClient, SearchResult
from src.search.scraper import WebScraper, ScrapeResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(api_key="test_key", cse_id="test_cx"):
    cfg = MagicMock()
    cfg.google_api_key = api_key
    cfg.google_cse_id = cse_id
    return cfg


def _make_rate_limiter():
    rl = MagicMock()
    rl.acquire = AsyncMock(return_value=None)
    return rl


def _cse_response(items):
    return {"items": items}


def _cse_item(title="Company", link="https://example.com", snippet="A company."):
    return {"title": title, "link": link, "snippet": snippet}


# ---------------------------------------------------------------------------
# GoogleSearchClient
# ---------------------------------------------------------------------------

class TestGoogleSearchClient:
    def _client(self):
        return GoogleSearchClient(_make_config(), _make_rate_limiter())

    @pytest.mark.asyncio
    async def test_search_formats_query_correctly(self):
        """search() must pass q, key, cx, num to the API."""
        client = self._client()
        captured_params = {}

        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(return_value=_cse_response([_cse_item()]))
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)

        original_get = MagicMock(return_value=resp)

        def capturing_get(url, params=None, timeout=None):
            captured_params.update(params or {})
            return resp

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = capturing_get

        with patch("src.search.google_search.aiohttp.ClientSession", return_value=mock_session):
            results = await client.search("acme corp", num_results=5)

        assert captured_params["q"] == "acme corp"
        assert captured_params["key"] == "test_key"
        assert captured_params["cx"] == "test_cx"
        assert captured_params["num"] == 5

    @pytest.mark.asyncio
    async def test_search_returns_search_result_objects(self):
        client = self._client()

        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(return_value=_cse_response([
            _cse_item(title="Acme Corp", link="https://acme.com", snippet="We build stuff."),
        ]))
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=resp)

        with patch("src.search.google_search.aiohttp.ClientSession", return_value=mock_session):
            results = await client.search("acme")

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].title == "Acme Corp"
        assert results[0].url == "https://acme.com"
        assert results[0].snippet == "We build stuff."

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_http_error(self):
        client = self._client()

        resp = AsyncMock()
        resp.status = 429
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=resp)

        with patch("src.search.google_search.aiohttp.ClientSession", return_value=mock_session):
            results = await client.search("anything")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_network_error(self):
        import aiohttp as _aiohttp
        client = self._client()

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(side_effect=_aiohttp.ClientConnectionError("refused"))

        with patch("src.search.google_search.aiohttp.ClientSession", return_value=mock_session):
            results = await client.search("anything")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_site_prepends_site_operator(self):
        client = self._client()
        captured_params = {}

        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(return_value=_cse_response([]))
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)

        def capturing_get(url, params=None, timeout=None):
            captured_params.update(params or {})
            return resp

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = capturing_get

        with patch("src.search.google_search.aiohttp.ClientSession", return_value=mock_session):
            await client.search_site("about", "acme.com")

        assert captured_params["q"] == "site:acme.com about"

    @pytest.mark.asyncio
    async def test_search_caps_num_results_at_10(self):
        client = self._client()
        captured_params = {}

        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(return_value=_cse_response([]))
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)

        def capturing_get(url, params=None, timeout=None):
            captured_params.update(params or {})
            return resp

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = capturing_get

        with patch("src.search.google_search.aiohttp.ClientSession", return_value=mock_session):
            await client.search("test", num_results=50)

        assert captured_params["num"] == 10

    @pytest.mark.asyncio
    async def test_rate_limiter_is_called(self):
        rl = _make_rate_limiter()
        client = GoogleSearchClient(_make_config(), rl)

        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(return_value=_cse_response([]))
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=resp)

        with patch("src.search.google_search.aiohttp.ClientSession", return_value=mock_session):
            await client.search("test")

        rl.acquire.assert_awaited_once_with("google_search")


# ---------------------------------------------------------------------------
# WebScraper
# ---------------------------------------------------------------------------

class TestWebScraper:
    def _scraper(self):
        return WebScraper()

    def _mock_session(self, status=200, text="<html><body><p>Hello world</p></body></html>"):
        resp = AsyncMock()
        resp.status = status
        resp.text = AsyncMock(return_value=text)
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=resp)
        return session

    @pytest.mark.asyncio
    async def test_scrape_to_markdown_returns_text_on_success(self):
        scraper = self._scraper()
        mock_session = self._mock_session(200, "<html><body><p>Company info here</p></body></html>")

        with patch("src.search.scraper.aiohttp.ClientSession", return_value=mock_session):
            result = await scraper.scrape_to_markdown("https://example.com")

        assert result is not None
        assert "Company info here" in result

    @pytest.mark.asyncio
    async def test_scrape_to_markdown_strips_nav_and_footer(self):
        scraper = self._scraper()
        html = (
            "<html><body>"
            "<nav>Navigation links</nav>"
            "<p>Main content</p>"
            "<footer>Footer text</footer>"
            "</body></html>"
        )
        mock_session = self._mock_session(200, html)

        with patch("src.search.scraper.aiohttp.ClientSession", return_value=mock_session):
            result = await scraper.scrape_to_markdown("https://example.com")

        assert "Main content" in result
        assert "Navigation links" not in result
        assert "Footer text" not in result

    @pytest.mark.asyncio
    async def test_scrape_to_markdown_returns_none_on_403(self):
        scraper = self._scraper()
        mock_session = self._mock_session(403)

        with patch("src.search.scraper.aiohttp.ClientSession", return_value=mock_session):
            result = await scraper.scrape_to_markdown("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_to_markdown_returns_none_on_404(self):
        scraper = self._scraper()
        mock_session = self._mock_session(404)

        with patch("src.search.scraper.aiohttp.ClientSession", return_value=mock_session):
            result = await scraper.scrape_to_markdown("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_to_markdown_returns_none_on_timeout(self):
        import aiohttp as _aiohttp
        scraper = self._scraper()

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(side_effect=_aiohttp.ServerTimeoutError())

        with patch("src.search.scraper.aiohttp.ClientSession", return_value=session):
            result = await scraper.scrape_to_markdown("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_to_markdown_returns_none_on_connection_refused(self):
        import aiohttp as _aiohttp
        scraper = self._scraper()

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(side_effect=_aiohttp.ClientConnectionError("refused"))

        with patch("src.search.scraper.aiohttp.ClientSession", return_value=session):
            result = await scraper.scrape_to_markdown("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_with_fallback_returns_primary_when_success(self):
        scraper = self._scraper()

        with patch.object(scraper, "scrape_to_markdown", AsyncMock(return_value="Primary content")):
            result = await scraper.scrape_with_fallback("Acme", "https://acme.com")

        assert result.is_primary is True
        assert result.partial is False
        assert result.content == "Primary content"
        assert result.source_url == "https://acme.com"

    @pytest.mark.asyncio
    async def test_scrape_with_fallback_tries_alternatives_on_failure(self):
        scraper = self._scraper()

        search_results = [
            SearchResult(title="Acme News", url="https://news.com/acme", snippet="..."),
            SearchResult(title="Acme Crunch", url="https://crunchbase.com/acme", snippet="..."),
            SearchResult(title="Acme LinkedIn", url="https://linkedin.com/acme", snippet="..."),
        ]

        mock_search_client = MagicMock()
        mock_search_client.search = AsyncMock(return_value=search_results)

        call_count = 0

        async def scrape_side_effect(url):
            nonlocal call_count
            call_count += 1
            if url == "https://acme.com":
                return None  # primary fails
            return f"Content from {url}"

        with patch.object(scraper, "scrape_to_markdown", side_effect=scrape_side_effect):
            result = await scraper.scrape_with_fallback(
                "Acme", "https://acme.com", search_client=mock_search_client
            )

        assert result.is_primary is False
        assert "https://news.com/acme" in result.content
        assert "https://crunchbase.com/acme" in result.content
        mock_search_client.search.assert_awaited_once_with("Acme", num_results=3)

    @pytest.mark.asyncio
    async def test_scrape_with_fallback_partial_when_some_alternatives_fail(self):
        scraper = self._scraper()

        search_results = [
            SearchResult(title="A", url="https://a.com", snippet=""),
            SearchResult(title="B", url="https://b.com", snippet=""),
        ]

        mock_search_client = MagicMock()
        mock_search_client.search = AsyncMock(return_value=search_results)

        async def scrape_side_effect(url):
            if url == "https://acme.com":
                return None
            if url == "https://a.com":
                return "Content A"
            return None  # b.com fails

        with patch.object(scraper, "scrape_to_markdown", side_effect=scrape_side_effect):
            result = await scraper.scrape_with_fallback(
                "Acme", "https://acme.com", search_client=mock_search_client
            )

        assert result.partial is True
        assert "Content A" in result.content

    @pytest.mark.asyncio
    async def test_scrape_with_fallback_no_search_client_returns_partial(self):
        scraper = self._scraper()

        with patch.object(scraper, "scrape_to_markdown", AsyncMock(return_value=None)):
            result = await scraper.scrape_with_fallback("Acme", "https://acme.com")

        assert result.is_primary is False
        assert result.partial is True
        assert result.content == ""

    @pytest.mark.asyncio
    async def test_scrape_with_fallback_handles_search_exception(self):
        scraper = self._scraper()

        mock_search_client = MagicMock()
        mock_search_client.search = AsyncMock(side_effect=Exception("network down"))

        with patch.object(scraper, "scrape_to_markdown", AsyncMock(return_value=None)):
            result = await scraper.scrape_with_fallback(
                "Acme", "https://acme.com", search_client=mock_search_client
            )

        assert result.is_primary is False
        assert result.partial is True
        assert result.content == ""
