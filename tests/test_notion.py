"""
Tests for Notion client, database CRUD, dedup logic, and setup.

All external API calls are mocked.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.notion.prop_helpers import title_prop, select_prop


@pytest.fixture
def mock_config():
    """Provide a mock config with test Notion credentials."""
    with patch("src.notion.client.get_config") as mock_cfg:
        cfg = MagicMock()
        cfg.notion_api_key = "test-api-key"
        cfg.notion_hub_page_id = "hub-page-id"
        cfg.notion_campaigns_db_id = "camp-db-id"
        cfg.notion_companies_db_id = "comp-db-id"
        cfg.notion_contacts_db_id = "cont-db-id"
        cfg.notion_emails_db_id = "email-db-id"
        cfg.enrichment_stale_days = 90
        mock_cfg.return_value = cfg
        yield cfg


@pytest.fixture
def mock_notion_sdk():
    """Provide a mocked Notion SDK client."""
    with patch("src.notion.client.NotionSDKClient") as mock_cls:
        sdk = MagicMock()
        mock_cls.return_value = sdk
        yield sdk


@pytest.fixture
def mock_limiter():
    """Provide a mock rate limiter that never blocks."""
    limiter = MagicMock()
    limiter.acquire = AsyncMock()
    return limiter


@pytest.mark.asyncio
async def test_client_query_pagination(mock_config, mock_notion_sdk, mock_limiter):
    """Verify query_database paginates through all results."""
    from src.notion.client import NotionClient
    mock_notion_sdk.databases.query.side_effect = [
        {"results": [{"id": "p1"}], "has_more": True, "next_cursor": "c1"},
        {"results": [{"id": "p2"}], "has_more": False, "next_cursor": None},
    ]
    client = NotionClient(rate_limiter=mock_limiter)
    results = await client.query_database("db-id")
    assert len(results) == 2
    assert mock_limiter.acquire.await_count == 2


@pytest.mark.asyncio
async def test_client_create_page(mock_config, mock_notion_sdk, mock_limiter):
    """Verify create_page calls SDK and acquires rate limiter slot."""
    from src.notion.client import NotionClient
    mock_notion_sdk.pages.create.return_value = {"id": "new-id"}
    client = NotionClient(rate_limiter=mock_limiter)
    result = await client.create_page("db-id", {"Name": title_prop("Test")})
    assert result["id"] == "new-id"
    mock_limiter.acquire.assert_awaited_once_with("notion")


@pytest.mark.asyncio
async def test_client_update_page(mock_config, mock_notion_sdk, mock_limiter):
    """Verify update_page forwards properties to SDK."""
    from src.notion.client import NotionClient
    mock_notion_sdk.pages.update.return_value = {"id": "page-id"}
    client = NotionClient(rate_limiter=mock_limiter)
    result = await client.update_page("page-id", {"Status": select_prop("Active")})
    assert result["id"] == "page-id"


# -- Companies dedup tests --


@pytest.mark.asyncio
async def test_companies_skip_recently_enriched(mock_config):
    """Test that creating a company is skipped if recently enriched."""
    with patch("src.notion.databases_companies.get_config") as cfg_mock:
        cfg_mock.return_value = mock_config

        from src.notion.databases_companies import CompaniesDB

        mock_client = MagicMock()
        recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        existing_page = {
            "id": "existing-id",
            "properties": {
                "Name": {"title": [{"plain_text": "Acme"}]},
                "Status": {"select": {"name": "Enriched"}},
                "Last Enriched": {"date": {"start": recent}},
                "Campaign": {"relation": [{"id": "camp-1"}]},
            },
        }
        mock_client.query_database = AsyncMock(return_value=[existing_page])
        mock_client.update_page = AsyncMock(return_value=existing_page)

        db = CompaniesDB(mock_client)
        result = await db.create_company("Acme", campaign_id="camp-1")
        assert result is None


@pytest.mark.asyncio
async def test_companies_link_new_campaign(mock_config):
    """Test that a new campaign is linked to existing company."""
    with patch("src.notion.databases_companies.get_config") as cfg_mock:
        cfg_mock.return_value = mock_config

        from src.notion.databases_companies import CompaniesDB

        mock_client = MagicMock()
        recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        existing_page = {
            "id": "existing-id",
            "properties": {
                "Name": {"title": [{"plain_text": "Acme"}]},
                "Status": {"select": {"name": "Enriched"}},
                "Last Enriched": {"date": {"start": recent}},
                "Campaign": {"relation": [{"id": "camp-1"}]},
            },
        }
        mock_client.query_database = AsyncMock(return_value=[existing_page])
        mock_client.update_page = AsyncMock(return_value=existing_page)

        db = CompaniesDB(mock_client)
        await db.create_company("Acme", campaign_id="camp-2")

        mock_client.update_page.assert_awaited_once()
        call_args = mock_client.update_page.call_args
        campaign_prop = call_args[0][1]["Campaign"]
        ids = [r["id"] for r in campaign_prop["relation"]]
        assert "camp-1" in ids
        assert "camp-2" in ids


# -- Contacts dedup tests --


@pytest.mark.asyncio
async def test_contacts_skip_existing_email(mock_config):
    """Test that creating a contact is skipped if email exists."""
    with patch("src.notion.databases_contacts.get_config") as cfg_mock:
        cfg_mock.return_value = mock_config

        from src.notion.databases_contacts import ContactsDB

        mock_client = MagicMock()
        existing = {
            "id": "existing-contact",
            "properties": {"Email": {"email": "john@acme.com"}},
        }
        mock_client.query_database = AsyncMock(return_value=[existing])

        db = ContactsDB(mock_client)
        result = await db.create_contact(
            "John Doe", "comp-1", "camp-1", email_addr="john@acme.com"
        )

        assert result is None
        mock_client.create_page.assert_not_called()


@pytest.mark.asyncio
async def test_contacts_create_new(mock_config):
    """Test that a contact is created when no email match exists."""
    with patch("src.notion.databases_contacts.get_config") as cfg_mock:
        cfg_mock.return_value = mock_config

        from src.notion.databases_contacts import ContactsDB

        mock_client = MagicMock()
        mock_client.query_database = AsyncMock(return_value=[])
        mock_client.create_page = AsyncMock(
            return_value={"id": "new-contact"}
        )

        db = ContactsDB(mock_client)
        result = await db.create_contact(
            "Jane Doe", "comp-1", "camp-1",
            email_addr="jane@acme.com", job_title="CEO",
        )

        assert result["id"] == "new-contact"
        mock_client.create_page.assert_awaited_once()


# -- Setup tests --


@pytest.mark.asyncio
async def test_setup_creates_all_databases():
    """Test that setup creates all four databases in order."""
    with patch("src.notion.setup.get_config") as cfg_mock:
        cfg = MagicMock()
        cfg.notion_hub_page_id = "hub-page-id"
        cfg.notion_campaigns_db_id = ""
        cfg.notion_companies_db_id = ""
        cfg.notion_contacts_db_id = ""
        cfg.notion_emails_db_id = ""
        cfg_mock.return_value = cfg

        from src.notion.setup import setup_databases

        mock_client = MagicMock()
        counter = {"n": 0}

        async def fake_create(parent_id, title, props):
            counter["n"] += 1
            return {"id": f"db-{counter['n']}"}

        mock_client.create_database = AsyncMock(side_effect=fake_create)
        result = await setup_databases(client=mock_client)

        assert result["campaigns"] == "db-1"
        assert result["companies"] == "db-2"
        assert result["contacts"] == "db-3"
        assert result["emails"] == "db-4"
        assert mock_client.create_database.await_count == 4


@pytest.mark.asyncio
async def test_setup_skips_existing():
    """Test that setup is idempotent with existing DB IDs."""
    with patch("src.notion.setup.get_config") as cfg_mock:
        cfg = MagicMock()
        cfg.notion_hub_page_id = "hub-page-id"
        cfg.notion_campaigns_db_id = "existing-camp-db"
        cfg.notion_companies_db_id = "existing-comp-db"
        cfg.notion_contacts_db_id = "existing-cont-db"
        cfg.notion_emails_db_id = "existing-email-db"
        cfg_mock.return_value = cfg

        from src.notion.setup import setup_databases

        mock_client = MagicMock()
        mock_client.create_database = AsyncMock()

        result = await setup_databases(client=mock_client)

        mock_client.create_database.assert_not_awaited()
        assert result["campaigns"] == "existing-camp-db"


# -- Email status tests --


@pytest.mark.asyncio
async def test_emails_status_validates(mock_config):
    """Test that updating email status rejects invalid values."""
    with patch("src.notion.databases_emails.get_config") as cfg_mock:
        cfg_mock.return_value = mock_config

        from src.notion.databases_emails import EmailsDB

        mock_client = MagicMock()
        db = EmailsDB(mock_client)

        with pytest.raises(ValueError, match="Invalid email status"):
            await db.update_status("page-id", "InvalidStatus")


@pytest.mark.asyncio
async def test_emails_sent_adds_date(mock_config):
    """Test that setting status to Sent also sets Sent At."""
    with patch("src.notion.databases_emails.get_config") as cfg_mock:
        cfg_mock.return_value = mock_config

        from src.notion.databases_emails import EmailsDB

        mock_client = MagicMock()
        mock_client.update_page = AsyncMock(
            return_value={"id": "email-1"}
        )

        db = EmailsDB(mock_client)
        await db.update_status("email-1", "Sent")

        call_args = mock_client.update_page.call_args
        props = call_args[0][1]
        assert "Sent At" in props
        assert props["Status"] == {"select": {"name": "Sent"}}
