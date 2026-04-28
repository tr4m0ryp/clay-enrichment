"""
Tests for the Layer 2 enrichment worker.

Covers per-company grounded enrichment, status updates (Enriched vs
Partially Enriched), fallback to scrape, stale company re-enrichment,
and error recovery.
All external clients are mocked.
"""

import asyncio
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.enrichment.worker import enrichment_worker
from src.enrichment.helpers import (
    build_enrichment_text,
    build_properties_update_pg,
    scrape_fallback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_company(
    page_id: str = "page-1",
    name: str = "TestBrand",
    website: str = "https://testbrand.com",
    status: str = "Discovered",
) -> dict:
    """Build a minimal flat company dict (Postgres row)."""
    return {
        "id": page_id,
        "name": name,
        "website": website,
        "status": status,
        "industry": "Fashion",
        "location": "Amsterdam",
        "size": "50-100",
        "dpp_fit_score": None,
    }


@dataclass
class FakeScrapeResult:
    content: str
    source_url: str
    is_primary: bool
    partial: bool


def _make_gemini_result(
    company_name: str = "TestBrand",
    score: int = 8,
) -> dict:
    return {
        "company_name": company_name,
        "industry": "Fashion",
        "location": "Amsterdam, Netherlands",
        "size": "50-100 employees",
        "products": ["sneakers", "streetwear"],
        "sustainability_focus": True,
        "premium_positioning": True,
        "eu_presence": "Active in 8 EU countries",
        "recent_news": "Launched new collection Q1 2026",
        "dpp_fit_score": score,
        "dpp_fit_reasoning": "Strong EU fashion brand with sustainability focus.",
        "key_selling_points": [
            "EU-based with wide distribution",
            "Existing sustainability program",
            "Strong brand identity",
        ],
        "company_summary": "TestBrand is a premium streetwear label.",
    }


def _make_config():
    cfg = MagicMock()
    cfg.enrichment_stale_days = 90
    cfg.model_research = "gemini-2.5-flash"
    cfg.model_enrichment = "gemini-2.5-flash-lite"
    return cfg


def _make_scraper(fail=False):
    scraper = MagicMock()
    if fail:
        scraper.scrape_with_fallback = AsyncMock(
            side_effect=Exception("scrape error")
        )
    else:
        scraper.scrape_with_fallback = AsyncMock(
            return_value=FakeScrapeResult(
                content="We are a fashion brand in Amsterdam.",
                source_url="https://testbrand.com",
                is_primary=True,
                partial=False,
            )
        )
    return scraper


def _make_gemini_client(
    research_text: str = "Research report for TestBrand",
    result_dict: dict | None = None,
    fail_research: bool = False,
    fail_structure: bool = False,
    fail_all: bool = False,
):
    """Build a mock GeminiClient with generate() for two-step pipeline."""
    client = MagicMock()
    if result_dict is None:
        result_dict = _make_gemini_result()

    if fail_all:
        client.generate = AsyncMock(side_effect=Exception("gemini error"))
        return client

    calls = []

    async def _generate_side_effect(**kwargs):
        calls.append(kwargs)
        if kwargs.get("grounding"):
            if fail_research:
                raise Exception("grounded research error")
            return {
                "text": research_text,
                "input_tokens": 100,
                "output_tokens": 200,
            }
        else:
            if fail_structure:
                raise Exception("structuring error")
            return {
                "text": json.dumps(result_dict),
                "input_tokens": 50,
                "output_tokens": 100,
            }

    client.generate = AsyncMock(side_effect=_generate_side_effect)
    client._calls = calls
    return client


def _make_companies_db():
    db = MagicMock()
    db.update_company = AsyncMock(return_value={"id": "page-1"})
    db.append_body = AsyncMock()
    db.get_companies_by_status = AsyncMock(return_value=[])
    db.get_stale_companies = AsyncMock(return_value=[])
    # Mock the _pool.fetch for campaign target lookup
    pool_mock = MagicMock()
    pool_mock.fetch = AsyncMock(return_value=[])
    db._pool = pool_mock
    return db


def _make_campaigns_db():
    db = MagicMock()
    db.get_processable_campaigns = AsyncMock(return_value=[])
    return db


def _make_search_client():
    client = MagicMock()
    client.search = AsyncMock(return_value=[])
    return client


# ---------------------------------------------------------------------------
# Tests: build_enrichment_text()
# ---------------------------------------------------------------------------


class TestBuildEnrichmentText:

    def test_produces_text(self):
        result = _make_gemini_result()
        text = build_enrichment_text(result)
        assert len(text) > 0
        assert isinstance(text, str)

    def test_contains_dpp_reasoning(self):
        result = _make_gemini_result(score=9)
        text = build_enrichment_text(result)
        assert "DPP Fit Assessment" in text

    def test_contains_selling_points(self):
        result = _make_gemini_result()
        text = build_enrichment_text(result)
        assert "EU-based" in text

    def test_contains_eu_presence(self):
        result = _make_gemini_result()
        text = build_enrichment_text(result)
        assert "EU Presence" in text

    def test_contains_recent_news(self):
        result = _make_gemini_result()
        text = build_enrichment_text(result)
        assert "Recent News" in text


# ---------------------------------------------------------------------------
# Tests: build_properties_update_pg()
# ---------------------------------------------------------------------------


class TestBuildPropertiesUpdatePg:

    def test_enriched_status(self):
        result = _make_gemini_result(score=8)
        props = build_properties_update_pg(result, "Enriched")
        assert props["status"] == "Enriched"
        assert "last_enriched_at" in props
        assert props["dpp_fit_score"] == 8

    def test_partial_status(self):
        result = _make_gemini_result()
        props = build_properties_update_pg(result, "Partially Enriched")
        assert props["status"] == "Partially Enriched"

    def test_invalid_industry_defaults_to_other(self):
        result = _make_gemini_result()
        result["industry"] = "Automotive"
        props = build_properties_update_pg(result, "Enriched")
        assert props["industry"] == "Other"

    def test_unknown_location_skipped(self):
        result = _make_gemini_result()
        result["location"] = "Unknown"
        props = build_properties_update_pg(result, "Enriched")
        assert "location" not in props

    def test_valid_location_included(self):
        result = _make_gemini_result()
        result["location"] = "Berlin, Germany"
        props = build_properties_update_pg(result, "Enriched")
        assert props["location"] == "Berlin, Germany"


# ---------------------------------------------------------------------------
# Tests: enrichment_worker()
# ---------------------------------------------------------------------------


class TestEnrichmentWorker:

    @pytest.mark.anyio
    async def test_worker_processes_discovered_companies(self):
        """Worker should fetch Discovered companies and enrich them."""
        page = _make_company()
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        companies_db.get_companies_by_status = AsyncMock(return_value=[page])
        campaigns_db = _make_campaigns_db()
        search_client = _make_search_client()

        with patch("src.enrichment.worker.CYCLE_SLEEP_SECONDS", 0), \
             patch("src.enrichment.worker.resolve_website", AsyncMock(return_value="https://testbrand.com")):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini,
                    companies_db, campaigns_db, scraper,
                    search_client,
                )
            )
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        companies_db.get_companies_by_status.assert_called_with("Discovered")
        companies_db.get_stale_companies.assert_called()
        gemini.generate.assert_called()

    @pytest.mark.anyio
    async def test_worker_uses_grounding_then_structuring(self):
        """Worker should make two generate calls: grounded then structured."""
        page = _make_company()
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        companies_db.get_companies_by_status = AsyncMock(return_value=[page])
        campaigns_db = _make_campaigns_db()
        search_client = _make_search_client()

        with patch("src.enrichment.worker.CYCLE_SLEEP_SECONDS", 0), \
             patch("src.enrichment.worker.resolve_website", AsyncMock(return_value="https://testbrand.com")):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini,
                    companies_db, campaigns_db, scraper,
                    search_client,
                )
            )
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert gemini.generate.call_count >= 2
        calls = gemini.generate.call_args_list
        first_call = calls[0]
        assert first_call.kwargs.get("grounding") is True
        second_call = calls[1]
        assert second_call.kwargs.get("json_mode") is True

    @pytest.mark.anyio
    async def test_worker_falls_back_to_scrape(self):
        """When grounded research fails, worker should fall back to scrape."""
        page = _make_company()
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client(fail_research=True)
        companies_db = _make_companies_db()
        companies_db.get_companies_by_status = AsyncMock(return_value=[page])
        campaigns_db = _make_campaigns_db()
        search_client = _make_search_client()

        fallback_result = _make_gemini_result()

        async def _fallback_generate(**kwargs):
            if kwargs.get("grounding"):
                raise Exception("grounded research error")
            return {
                "text": json.dumps([fallback_result]),
                "input_tokens": 50,
                "output_tokens": 100,
            }

        gemini.generate = AsyncMock(side_effect=_fallback_generate)

        with patch("src.enrichment.worker.CYCLE_SLEEP_SECONDS", 0), \
             patch("src.enrichment.worker.resolve_website", AsyncMock(return_value="https://testbrand.com")):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini,
                    companies_db, campaigns_db, scraper,
                    search_client,
                )
            )
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        update_calls = companies_db.update_company.call_args_list
        statuses = []
        for call in update_calls:
            props = call[0][1]
            if "status" in props:
                statuses.append(props["status"])
        assert "Partially Enriched" in statuses

    @pytest.mark.anyio
    async def test_worker_includes_stale_companies(self):
        """Worker should also include stale companies."""
        discovered = _make_company(page_id="p1", name="Discovered Co")
        stale = _make_company(page_id="p2", name="Stale Co")

        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        companies_db.get_companies_by_status = AsyncMock(return_value=[discovered])
        companies_db.get_stale_companies = AsyncMock(return_value=[stale])
        campaigns_db = _make_campaigns_db()
        search_client = _make_search_client()

        with patch("src.enrichment.worker.CYCLE_SLEEP_SECONDS", 0), \
             patch("src.enrichment.worker.resolve_website", AsyncMock(return_value="")):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini,
                    companies_db, campaigns_db, scraper,
                    search_client,
                )
            )
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert gemini.generate.call_count >= 4

    @pytest.mark.anyio
    async def test_worker_deduplicates_companies(self):
        """Same company in both Discovered and stale should be processed once."""
        page = _make_company(page_id="same-id", name="DupeCo")

        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        companies_db.get_companies_by_status = AsyncMock(return_value=[page])
        companies_db.get_stale_companies = AsyncMock(return_value=[page])
        campaigns_db = _make_campaigns_db()
        search_client = _make_search_client()

        with patch("src.enrichment.worker.CYCLE_SLEEP_SECONDS", 0), \
             patch("src.enrichment.worker.resolve_website", AsyncMock(return_value="")):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini,
                    companies_db, campaigns_db, scraper,
                    search_client,
                )
            )
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert gemini.generate.call_count >= 2
        assert gemini.generate.call_count % 2 == 0

    @pytest.mark.anyio
    async def test_worker_survives_cycle_error(self):
        """Worker should not crash if a cycle raises an exception."""
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        companies_db.get_companies_by_status = AsyncMock(
            side_effect=Exception("DB error")
        )
        campaigns_db = _make_campaigns_db()
        search_client = _make_search_client()

        with patch("src.enrichment.worker.CYCLE_SLEEP_SECONDS", 0):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini,
                    companies_db, campaigns_db, scraper,
                    search_client,
                )
            )
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert companies_db.get_companies_by_status.call_count >= 1

    @pytest.mark.anyio
    async def test_worker_no_companies_is_noop(self):
        """Worker should do nothing when no companies need enrichment."""
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        campaigns_db = _make_campaigns_db()
        search_client = _make_search_client()

        with patch("src.enrichment.worker.CYCLE_SLEEP_SECONDS", 0):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini,
                    companies_db, campaigns_db, scraper,
                    search_client,
                )
            )
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        gemini.generate.assert_not_called()
