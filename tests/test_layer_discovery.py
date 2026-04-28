"""
Tests for Layer 1: Company Discovery Worker.

Covers the discovery worker loop, per-campaign flow, dedup logic,
and error recovery with fully mocked Gemini, DB, and Search clients.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.discovery.worker import (
    DBClients,
    discover_companies_for_campaign,
    discovery_worker,
    _generate_search_queries,
    _execute_searches,
    _parse_search_results,
    _write_companies,
)
from src.search.google_search import SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_campaign(
    page_id: str = "camp-1",
    name: str = "Test Campaign",
    target: str = "EU fashion brands with sustainability focus",
    status: str = "Active",
) -> dict:
    """Build a minimal flat campaign dict (Postgres row)."""
    return {
        "id": page_id,
        "name": name,
        "target_description": target,
        "status": status,
    }


def _make_config():
    """Build a minimal config-like object with model_discovery."""
    cfg = MagicMock()
    cfg.model_discovery = "gemini-2.5-flash-lite"
    return cfg


def _make_db_clients(
    campaigns_return: list | None = None,
    find_by_name_return=None,
    create_company_return=None,
):
    """Build a DBClients mock with campaigns and companies stubs."""
    campaigns_db = AsyncMock()
    campaigns_db.get_active_campaigns = AsyncMock(
        return_value=campaigns_return or []
    )

    companies_db = AsyncMock()
    companies_db.find_by_name = AsyncMock(return_value=find_by_name_return)
    companies_db.create_company = AsyncMock(
        return_value=create_company_return or {"id": "new-company-id"}
    )

    return DBClients(campaigns=campaigns_db, companies=companies_db)


def _make_gemini_client(generate_return=None):
    """Build a mock GeminiClient."""
    client = AsyncMock()
    client.generate = AsyncMock(
        return_value=generate_return
        or {"text": "[]", "input_tokens": 10, "output_tokens": 5}
    )
    return client


def _make_search_client(search_return=None):
    """Build a mock GoogleSearchClient."""
    client = AsyncMock()
    client.search = AsyncMock(return_value=search_return or [])
    return client


# ---------------------------------------------------------------------------
# Query generation tests
# ---------------------------------------------------------------------------


class TestGenerateSearchQueries:
    """Tests for _generate_search_queries."""

    @pytest.mark.asyncio
    async def test_returns_query_list(self):
        queries = ["EU sustainable fashion brands", "Danish streetwear DTC"]
        gemini = _make_gemini_client(
            generate_return={
                "text": json.dumps(queries),
                "input_tokens": 100,
                "output_tokens": 50,
            }
        )
        config = _make_config()
        result = await _generate_search_queries(
            gemini, config, "EU fashion target"
        )
        assert result == queries

    @pytest.mark.asyncio
    async def test_filters_non_string_items(self):
        gemini = _make_gemini_client(
            generate_return={
                "text": json.dumps(["valid query", 123, None, "", "another"]),
                "input_tokens": 10,
                "output_tokens": 10,
            }
        )
        config = _make_config()
        result = await _generate_search_queries(
            gemini, config, "target"
        )
        assert result == ["valid query", "another"]

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self):
        gemini = _make_gemini_client(
            generate_return={
                "text": "not valid json",
                "input_tokens": 10,
                "output_tokens": 10,
            }
        )
        config = _make_config()
        result = await _generate_search_queries(
            gemini, config, "target"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_non_array_json(self):
        gemini = _make_gemini_client(
            generate_return={
                "text": json.dumps({"queries": ["a", "b"]}),
                "input_tokens": 10,
                "output_tokens": 10,
            }
        )
        config = _make_config()
        result = await _generate_search_queries(
            gemini, config, "target"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_uses_discovery_model(self):
        gemini = _make_gemini_client()
        config = _make_config()
        config.model_discovery = "gemini-test-model"
        await _generate_search_queries(gemini, config, "target")
        call_kwargs = gemini.generate.call_args
        assert call_kwargs.kwargs.get("model") == "gemini-test-model"


# ---------------------------------------------------------------------------
# Search execution tests
# ---------------------------------------------------------------------------


class TestExecuteSearches:
    """Tests for _execute_searches."""

    @pytest.mark.asyncio
    async def test_collects_results_from_all_queries(self):
        search_client = _make_search_client(
            search_return=[
                SearchResult(title="Result 1", url="https://example.com", snippet="Snippet 1"),
            ]
        )
        results = await _execute_searches(search_client, ["query1", "query2"])
        assert len(results) == 2
        assert results[0]["source_query"] == "query1"
        assert results[1]["source_query"] == "query2"

    @pytest.mark.asyncio
    async def test_handles_search_error_gracefully(self):
        search_client = AsyncMock()
        search_client.search = AsyncMock(
            side_effect=[
                [SearchResult(title="OK", url="https://ok.com", snippet="ok")],
                Exception("API error"),
                [SearchResult(title="Also OK", url="https://also.com", snippet="also")],
            ]
        )
        results = await _execute_searches(
            search_client, ["q1", "q2", "q3"]
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_empty_queries_returns_empty(self):
        search_client = _make_search_client()
        results = await _execute_searches(search_client, [])
        assert results == []


# ---------------------------------------------------------------------------
# Result parsing tests
# ---------------------------------------------------------------------------


class TestParseSearchResults:
    """Tests for _parse_search_results."""

    @pytest.mark.asyncio
    async def test_extracts_companies(self):
        companies = [
            {
                "company_name": "TestBrand",
                "website_url": "https://testbrand.com",
                "reasoning": "EU streetwear brand",
            }
        ]
        gemini = _make_gemini_client(
            generate_return={
                "text": json.dumps(companies),
                "input_tokens": 100,
                "output_tokens": 50,
            }
        )
        config = _make_config()
        result = await _parse_search_results(
            gemini, config, "target", [{"title": "r", "url": "u", "snippet": "s"}]
        )
        assert len(result) == 1
        assert result[0]["company_name"] == "TestBrand"

    @pytest.mark.asyncio
    async def test_filters_entries_without_name(self):
        companies = [
            {"company_name": "GoodCo", "website_url": "", "reasoning": "ok"},
            {"website_url": "https://no-name.com", "reasoning": "missing name"},
            {"company_name": "", "website_url": "", "reasoning": "empty name"},
        ]
        gemini = _make_gemini_client(
            generate_return={
                "text": json.dumps(companies),
                "input_tokens": 10,
                "output_tokens": 10,
            }
        )
        config = _make_config()
        result = await _parse_search_results(
            gemini, config, "target", [{"title": "r", "url": "u", "snippet": "s"}]
        )
        assert len(result) == 1
        assert result[0]["company_name"] == "GoodCo"

    @pytest.mark.asyncio
    async def test_handles_parse_failure(self):
        gemini = _make_gemini_client(
            generate_return={
                "text": "invalid json garbage",
                "input_tokens": 10,
                "output_tokens": 10,
            }
        )
        config = _make_config()
        result = await _parse_search_results(
            gemini, config, "target", [{"title": "r", "url": "u", "snippet": "s"}]
        )
        assert result == []


# ---------------------------------------------------------------------------
# Company writing / dedup tests
# ---------------------------------------------------------------------------


class TestWriteCompanies:
    """Tests for _write_companies dedup and creation logic."""

    @pytest.mark.asyncio
    async def test_creates_new_company(self):
        db = _make_db_clients(find_by_name_return=None)
        companies = [
            {"company_name": "NewBrand", "website_url": "https://new.com", "reasoning": "good fit"}
        ]
        new_count, existing_count = await _write_companies(
            db.companies, companies, "camp-1"
        )
        assert new_count == 1
        assert existing_count == 0
        db.companies.create_company.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_company_counted(self):
        existing_page = _make_campaign(page_id="existing-co")
        db = _make_db_clients(find_by_name_return=existing_page)
        companies = [
            {"company_name": "ExistingCo", "website_url": "", "reasoning": ""}
        ]
        new_count, existing_count = await _write_companies(
            db.companies, companies, "camp-1"
        )
        assert existing_count == 1
        # create_company still called to handle campaign linking
        assert db.companies.create_company.call_count == 1

    @pytest.mark.asyncio
    async def test_skips_empty_names(self):
        db = _make_db_clients()
        companies = [
            {"company_name": "", "website_url": "", "reasoning": ""},
            {"company_name": "   ", "website_url": "", "reasoning": ""},
        ]
        new_count, existing_count = await _write_companies(
            db.companies, companies, "camp-1"
        )
        assert new_count == 0
        assert existing_count == 0
        db.companies.find_by_name.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_write_error(self):
        db = _make_db_clients()
        db.companies.find_by_name = AsyncMock(
            side_effect=Exception("DB error")
        )
        companies = [
            {"company_name": "FailCo", "website_url": "", "reasoning": ""},
            {"company_name": "OKCo", "website_url": "", "reasoning": ""},
        ]
        # Second call succeeds
        db.companies.find_by_name = AsyncMock(
            side_effect=[Exception("fail"), None]
        )
        db.companies.create_company = AsyncMock(
            return_value={"id": "ok-co-id"}
        )
        new_count, existing_count = await _write_companies(
            db.companies, companies, "camp-1"
        )
        # First fails, second succeeds
        assert new_count == 1
        assert existing_count == 0

    @pytest.mark.asyncio
    async def test_multiple_companies_mixed(self):
        existing_page = _make_campaign(page_id="existing-co")

        db = _make_db_clients()
        db.companies.find_by_name = AsyncMock(
            side_effect=[None, existing_page, None]
        )
        db.companies.create_company = AsyncMock(
            return_value={"id": "new-id"}
        )

        companies = [
            {"company_name": "NewOne", "website_url": "", "reasoning": ""},
            {"company_name": "OldOne", "website_url": "", "reasoning": ""},
            {"company_name": "NewTwo", "website_url": "", "reasoning": ""},
        ]

        new_count, existing_count = await _write_companies(
            db.companies, companies, "camp-1"
        )
        assert new_count == 2
        assert existing_count == 1


# ---------------------------------------------------------------------------
# Per-campaign flow tests
# ---------------------------------------------------------------------------


class TestDiscoverCompaniesForCampaign:
    """Tests for discover_companies_for_campaign integration."""

    @pytest.mark.asyncio
    async def test_full_flow(self):
        campaign = _make_campaign()
        config = _make_config()

        queries = ["EU fashion brands"]
        extracted = [
            {"company_name": "BrandX", "website_url": "https://brandx.com", "reasoning": "good"}
        ]

        gemini = AsyncMock()
        gemini.generate = AsyncMock(
            side_effect=[
                {"text": json.dumps(queries), "input_tokens": 10, "output_tokens": 5},
                {"text": json.dumps(extracted), "input_tokens": 10, "output_tokens": 5},
            ]
        )

        search = _make_search_client(
            search_return=[
                SearchResult(title="BrandX", url="https://brandx.com", snippet="EU brand")
            ]
        )

        db = _make_db_clients(find_by_name_return=None)

        await discover_companies_for_campaign(
            campaign, config, gemini, db, search
        )

        db.companies.create_company.assert_called_once()
        call_kwargs = db.companies.create_company.call_args.kwargs
        assert call_kwargs["name"] == "BrandX"
        assert call_kwargs["campaign_id"] == "camp-1"

    @pytest.mark.asyncio
    async def test_skips_campaign_without_target(self):
        campaign = _make_campaign(target="")
        config = _make_config()
        gemini = _make_gemini_client()
        search = _make_search_client()
        db = _make_db_clients()

        await discover_companies_for_campaign(
            campaign, config, gemini, db, search
        )

        # Gemini should never be called if there is no target
        gemini.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_no_queries(self):
        campaign = _make_campaign()
        config = _make_config()
        gemini = _make_gemini_client(
            generate_return={"text": "[]", "input_tokens": 0, "output_tokens": 0}
        )
        search = _make_search_client()
        db = _make_db_clients()

        await discover_companies_for_campaign(
            campaign, config, gemini, db, search
        )

        search.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_no_search_results(self):
        campaign = _make_campaign()
        config = _make_config()
        gemini = _make_gemini_client(
            generate_return={
                "text": json.dumps(["query1"]),
                "input_tokens": 10,
                "output_tokens": 5,
            }
        )
        search = _make_search_client(search_return=[])
        db = _make_db_clients()

        await discover_companies_for_campaign(
            campaign, config, gemini, db, search
        )

        # Only query generation call, no parse call
        assert gemini.generate.call_count == 1


# ---------------------------------------------------------------------------
# Worker loop tests
# ---------------------------------------------------------------------------


class TestDiscoveryWorker:
    """Tests for the top-level discovery_worker loop."""

    @pytest.mark.asyncio
    async def test_polls_campaigns_and_processes(self):
        """Worker should poll campaigns and process each one."""
        campaign = _make_campaign()
        config = _make_config()
        gemini = _make_gemini_client()
        search = _make_search_client()
        db = _make_db_clients(campaigns_return=[campaign])

        iteration_count = 0

        original_sleep = asyncio.sleep

        async def _mock_sleep(seconds):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count >= 1:
                raise KeyboardInterrupt("stop loop")

        with patch("src.discovery.worker.asyncio.sleep", side_effect=_mock_sleep):
            with pytest.raises(KeyboardInterrupt):
                await discovery_worker(config, gemini, db, search)

        db.campaigns.get_active_campaigns.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_in_one_campaign_does_not_stop_others(self):
        """An exception in one campaign should not prevent processing others."""
        camp1 = _make_campaign(page_id="c1", name="Camp1")
        camp2 = _make_campaign(page_id="c2", name="Camp2")
        config = _make_config()

        call_count = 0

        async def _mock_discover(campaign, cfg, gem, db, search):
            nonlocal call_count
            call_count += 1
            if campaign["id"] == "c1":
                raise RuntimeError("simulated failure")

        gemini = _make_gemini_client()
        search = _make_search_client()
        db = _make_db_clients(campaigns_return=[camp1, camp2])

        iteration_count = 0

        async def _mock_sleep(seconds):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count >= 1:
                raise KeyboardInterrupt("stop loop")

        with patch(
            "src.discovery.worker.discover_companies_for_campaign",
            side_effect=_mock_discover,
        ):
            with patch(
                "src.discovery.worker.asyncio.sleep",
                side_effect=_mock_sleep,
            ):
                with pytest.raises(KeyboardInterrupt):
                    await discovery_worker(config, gemini, db, search)

        # Both campaigns should have been attempted
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_continues_after_campaign_fetch_error(self):
        """If fetching campaigns fails, the worker should sleep and retry."""
        config = _make_config()
        gemini = _make_gemini_client()
        search = _make_search_client()
        db = _make_db_clients()

        call_count = 0
        db.campaigns.get_active_campaigns = AsyncMock(
            side_effect=Exception("DB down")
        )

        async def _mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise KeyboardInterrupt("stop loop")

        with patch("src.discovery.worker.asyncio.sleep", side_effect=_mock_sleep):
            with pytest.raises(KeyboardInterrupt):
                await discovery_worker(config, gemini, db, search)

        # Sleep was called (recovery path)
        assert call_count >= 1
