"""
Tests for the Layer 2 enrichment worker.

Covers batching logic, status updates (Enriched vs Partially Enriched),
stale company re-enrichment, and error recovery per company.
All external clients are mocked.
"""

import asyncio
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.layers.enrichment import (
    chunk,
    enrich_batch,
    enrichment_worker,
    _build_enrichment_blocks,
    _build_properties_update,
    BATCH_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_company_page(
    page_id: str = "page-1",
    name: str = "TestBrand",
    website: str = "https://testbrand.com",
    status: str = "Discovered",
    campaign_ids: list[str] | None = None,
) -> dict:
    """Build a minimal Notion company page dict for testing."""
    if campaign_ids is None:
        campaign_ids = ["campaign-1"]

    return {
        "id": page_id,
        "properties": {
            "Name": {"title": [{"plain_text": name}]},
            "Website": {"url": website},
            "Status": {"select": {"name": status}},
            "Campaign": {"relation": [{"id": cid} for cid in campaign_ids]},
            "Last Enriched": {"date": None},
        },
    }


def _make_campaign_page(
    page_id: str = "campaign-1",
    target_description: str = "EU fashion brands",
) -> dict:
    return {
        "id": page_id,
        "properties": {
            "Name": {"title": [{"plain_text": "Test Campaign"}]},
            "Target Description": {
                "rich_text": [{"plain_text": target_description}]
            },
            "Status": {"select": {"name": "Active"}},
        },
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
    return cfg


def _make_scraper(results=None, fail=False):
    scraper = MagicMock()
    if fail:
        scraper.scrape_with_fallback = AsyncMock(
            side_effect=Exception("scrape error")
        )
    elif results is not None:
        scraper.scrape_with_fallback = AsyncMock(side_effect=results)
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


def _make_gemini_client(results=None, fail=False):
    client = MagicMock()
    if fail:
        client.generate_batch = AsyncMock(
            side_effect=Exception("gemini error")
        )
    elif results is not None:
        client.generate_batch = AsyncMock(
            return_value={
                "results": results,
                "input_tokens": 100,
                "output_tokens": 50,
            }
        )
    else:
        client.generate_batch = AsyncMock(
            return_value={
                "results": [_make_gemini_result()],
                "input_tokens": 100,
                "output_tokens": 50,
            }
        )
    return client


def _make_companies_db():
    db = MagicMock()
    db.update_company = AsyncMock(return_value={"id": "page-1"})
    db.get_companies_by_status = AsyncMock(return_value=[])
    db.get_stale_companies = AsyncMock(return_value=[])
    return db


def _make_campaigns_db(campaigns=None):
    db = MagicMock()
    if campaigns is None:
        campaigns = [_make_campaign_page()]
    db.get_active_campaigns = AsyncMock(return_value=campaigns)
    return db


def _make_notion_client():
    client = MagicMock()
    client.append_page_body = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Tests: chunk()
# ---------------------------------------------------------------------------


class TestChunk:

    def test_empty_list(self):
        assert chunk([], 3) == []

    def test_exact_multiple(self):
        result = chunk([1, 2, 3, 4, 5, 6], 3)
        assert result == [[1, 2, 3], [4, 5, 6]]

    def test_remainder(self):
        result = chunk([1, 2, 3, 4, 5], 3)
        assert result == [[1, 2, 3], [4, 5]]

    def test_smaller_than_size(self):
        result = chunk([1, 2], 3)
        assert result == [[1, 2]]

    def test_size_one(self):
        result = chunk([1, 2, 3], 1)
        assert result == [[1], [2], [3]]

    def test_default_batch_size(self):
        result = chunk([1, 2, 3, 4])
        assert len(result[0]) == BATCH_SIZE


# ---------------------------------------------------------------------------
# Tests: _build_enrichment_blocks()
# ---------------------------------------------------------------------------


class TestBuildEnrichmentBlocks:

    def test_produces_blocks(self):
        result = _make_gemini_result()
        blocks = _build_enrichment_blocks(result)
        assert len(blocks) > 0
        assert all(isinstance(b, dict) for b in blocks)

    def test_contains_score(self):
        result = _make_gemini_result(score=9)
        blocks = _build_enrichment_blocks(result)
        texts = []
        for b in blocks:
            btype = b.get("type", "")
            if btype in ("paragraph", "bulleted_list_item", "heading_2"):
                rich = b.get(btype, {}).get("rich_text", [])
                for rt in rich:
                    texts.append(rt.get("text", {}).get("content", ""))
        combined = " ".join(texts)
        assert "9/10" in combined

    def test_contains_selling_points(self):
        result = _make_gemini_result()
        blocks = _build_enrichment_blocks(result)
        bullet_texts = []
        for b in blocks:
            if b.get("type") == "bulleted_list_item":
                rich = b["bulleted_list_item"].get("rich_text", [])
                for rt in rich:
                    bullet_texts.append(rt.get("text", {}).get("content", ""))
        assert any("EU-based" in t for t in bullet_texts)


# ---------------------------------------------------------------------------
# Tests: _build_properties_update()
# ---------------------------------------------------------------------------


class TestBuildPropertiesUpdate:

    def test_enriched_status(self):
        result = _make_gemini_result(score=8)
        props = _build_properties_update(result, "Enriched")
        assert props["Status"] == {"select": {"name": "Enriched"}}
        assert "Last Enriched" in props
        assert props["DPP Fit Score"] == {"number": 8}

    def test_partial_status(self):
        result = _make_gemini_result()
        props = _build_properties_update(result, "Partially Enriched")
        assert props["Status"] == {"select": {"name": "Partially Enriched"}}

    def test_invalid_industry_defaults_to_other(self):
        result = _make_gemini_result()
        result["industry"] = "Automotive"
        props = _build_properties_update(result, "Enriched")
        assert props["Industry"] == {"select": {"name": "Other"}}

    def test_unknown_location_skipped(self):
        result = _make_gemini_result()
        result["location"] = "Unknown"
        props = _build_properties_update(result, "Enriched")
        assert "Location" not in props

    def test_valid_location_included(self):
        result = _make_gemini_result()
        result["location"] = "Berlin, Germany"
        props = _build_properties_update(result, "Enriched")
        assert "Location" in props


# ---------------------------------------------------------------------------
# Tests: enrich_batch()
# ---------------------------------------------------------------------------


class TestEnrichBatch:

    @pytest.mark.anyio
    async def test_single_company_enriched(self):
        """Single company with successful scrape should be marked Enriched."""
        page = _make_company_page()
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        await enrich_batch(
            [page], config, gemini, notion_client, companies_db, campaigns_db, scraper
        )

        # Should have called update_company with Enriched status
        companies_db.update_company.assert_called()
        call_args = companies_db.update_company.call_args_list[0]
        props = call_args[0][1]
        assert props["Status"] == {"select": {"name": "Enriched"}}

        # Should have appended page body
        notion_client.append_page_body.assert_called_once()

    @pytest.mark.anyio
    async def test_batch_of_three(self):
        """Three companies should produce one Gemini call."""
        pages = [
            _make_company_page(page_id=f"p{i}", name=f"Brand{i}")
            for i in range(3)
        ]
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client(
            results=[_make_gemini_result(f"Brand{i}") for i in range(3)]
        )
        companies_db = _make_companies_db()
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        await enrich_batch(
            pages, config, gemini, notion_client, companies_db, campaigns_db, scraper
        )

        # Exactly one Gemini batch call
        assert gemini.generate_batch.call_count == 1

        # Three items passed to Gemini
        call_kwargs = gemini.generate_batch.call_args
        assert len(call_kwargs.kwargs.get("items", call_kwargs[1].get("items", []))) == 3

        # All three companies updated
        assert companies_db.update_company.call_count == 3
        assert notion_client.append_page_body.call_count == 3

    @pytest.mark.anyio
    async def test_partial_scrape_sets_partially_enriched(self):
        """Company with partial scrape data should be Partially Enriched."""
        page = _make_company_page()
        config = _make_config()

        partial_result = FakeScrapeResult(
            content="Partial data",
            source_url="https://fallback.com",
            is_primary=False,
            partial=True,
        )
        scraper = _make_scraper(results=[partial_result])
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        await enrich_batch(
            [page], config, gemini, notion_client, companies_db, campaigns_db, scraper
        )

        call_args = companies_db.update_company.call_args_list[0]
        props = call_args[0][1]
        assert props["Status"] == {"select": {"name": "Partially Enriched"}}

    @pytest.mark.anyio
    async def test_all_scrapes_failed(self):
        """If all scrapes fail, companies should be Partially Enriched."""
        page = _make_company_page()
        config = _make_config()
        scraper = _make_scraper(fail=True)
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        await enrich_batch(
            [page], config, gemini, notion_client, companies_db, campaigns_db, scraper
        )

        # Gemini should NOT be called
        gemini.generate_batch.assert_not_called()

        # Company should be marked Partially Enriched
        companies_db.update_company.assert_called()
        call_args = companies_db.update_company.call_args_list[0]
        props = call_args[0][1]
        assert props["Status"] == {"select": {"name": "Partially Enriched"}}

    @pytest.mark.anyio
    async def test_gemini_failure_marks_partial(self):
        """If Gemini call fails, all companies should be Partially Enriched."""
        page = _make_company_page()
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client(fail=True)
        companies_db = _make_companies_db()
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        await enrich_batch(
            [page], config, gemini, notion_client, companies_db, campaigns_db, scraper
        )

        companies_db.update_company.assert_called()
        call_args = companies_db.update_company.call_args_list[0]
        props = call_args[0][1]
        assert props["Status"] == {"select": {"name": "Partially Enriched"}}

    @pytest.mark.anyio
    async def test_empty_batch(self):
        """Empty batch should be a no-op."""
        config = _make_config()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()
        scraper = _make_scraper()

        await enrich_batch(
            [], config, gemini, notion_client, companies_db, campaigns_db, scraper
        )

        gemini.generate_batch.assert_not_called()
        companies_db.update_company.assert_not_called()

    @pytest.mark.anyio
    async def test_mixed_scrape_success_and_failure(self):
        """One successful and one failed scrape in same batch."""
        pages = [
            _make_company_page(page_id="p1", name="GoodBrand"),
            _make_company_page(page_id="p2", name="BadBrand"),
        ]
        config = _make_config()

        good_scrape = FakeScrapeResult(
            content="Good brand content",
            source_url="https://goodbrand.com",
            is_primary=True,
            partial=False,
        )
        scraper = MagicMock()
        scraper.scrape_with_fallback = AsyncMock(
            side_effect=[good_scrape, Exception("network error")]
        )

        gemini = _make_gemini_client(results=[_make_gemini_result("GoodBrand")])
        companies_db = _make_companies_db()
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        await enrich_batch(
            pages, config, gemini, notion_client, companies_db, campaigns_db, scraper
        )

        # Gemini should be called with 1 item (only the successful scrape)
        call_kwargs = gemini.generate_batch.call_args
        items = call_kwargs.kwargs.get("items", call_kwargs[1].get("items", []))
        assert len(items) == 1

        # Both companies should be updated (one Enriched, one Partially Enriched)
        assert companies_db.update_company.call_count == 2

    @pytest.mark.anyio
    async def test_no_website_marks_partial(self):
        """Company with no website should be marked Partially Enriched."""
        page = _make_company_page(website="")
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        await enrich_batch(
            [page], config, gemini, notion_client, companies_db, campaigns_db, scraper
        )

        # Scraper should NOT be called (no URL)
        scraper.scrape_with_fallback.assert_not_called()

        companies_db.update_company.assert_called()
        call_args = companies_db.update_company.call_args_list[0]
        props = call_args[0][1]
        assert props["Status"] == {"select": {"name": "Partially Enriched"}}


# ---------------------------------------------------------------------------
# Tests: enrichment_worker()
# ---------------------------------------------------------------------------


class TestEnrichmentWorker:

    @pytest.mark.anyio
    async def test_worker_processes_discovered_companies(self):
        """Worker should fetch Discovered companies and enrich them."""
        page = _make_company_page()
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        companies_db.get_companies_by_status = AsyncMock(return_value=[page])
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        # Run one iteration then cancel
        with patch("src.layers.enrichment.CYCLE_SLEEP_SECONDS", 0):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini, notion_client,
                    companies_db, campaigns_db, scraper,
                )
            )
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        companies_db.get_companies_by_status.assert_called_with("Discovered")
        companies_db.get_stale_companies.assert_called()

    @pytest.mark.anyio
    async def test_worker_includes_stale_companies(self):
        """Worker should also include stale companies in the batch."""
        discovered = _make_company_page(page_id="p1", name="Discovered Co")
        stale = _make_company_page(page_id="p2", name="Stale Co")

        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client(
            results=[_make_gemini_result("Discovered Co"), _make_gemini_result("Stale Co")]
        )
        companies_db = _make_companies_db()
        companies_db.get_companies_by_status = AsyncMock(return_value=[discovered])
        companies_db.get_stale_companies = AsyncMock(return_value=[stale])
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        with patch("src.layers.enrichment.CYCLE_SLEEP_SECONDS", 0):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini, notion_client,
                    companies_db, campaigns_db, scraper,
                )
            )
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Both companies should be processed
        assert companies_db.update_company.call_count >= 2

    @pytest.mark.anyio
    async def test_worker_deduplicates_companies(self):
        """Same company in both Discovered and stale should be processed once."""
        page = _make_company_page(page_id="same-id", name="DupeCo")

        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        companies_db.get_companies_by_status = AsyncMock(return_value=[page])
        companies_db.get_stale_companies = AsyncMock(return_value=[page])
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        with patch("src.layers.enrichment.CYCLE_SLEEP_SECONDS", 0):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini, notion_client,
                    companies_db, campaigns_db, scraper,
                )
            )
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Gemini should process only 1 item (deduplicated)
        if gemini.generate_batch.called:
            call_kwargs = gemini.generate_batch.call_args
            items = call_kwargs.kwargs.get("items", call_kwargs[1].get("items", []))
            assert len(items) == 1

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
        notion_client = _make_notion_client()

        with patch("src.layers.enrichment.CYCLE_SLEEP_SECONDS", 0):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini, notion_client,
                    companies_db, campaigns_db, scraper,
                )
            )
            # Let it run two iterations (should survive the error)
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Worker survived -- the call was made (and failed)
        assert companies_db.get_companies_by_status.call_count >= 1

    @pytest.mark.anyio
    async def test_worker_no_companies_is_noop(self):
        """Worker should do nothing when no companies need enrichment."""
        config = _make_config()
        scraper = _make_scraper()
        gemini = _make_gemini_client()
        companies_db = _make_companies_db()
        campaigns_db = _make_campaigns_db()
        notion_client = _make_notion_client()

        with patch("src.layers.enrichment.CYCLE_SLEEP_SECONDS", 0):
            task = asyncio.create_task(
                enrichment_worker(
                    config, gemini, notion_client,
                    companies_db, campaigns_db, scraper,
                )
            )
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        gemini.generate_batch.assert_not_called()
