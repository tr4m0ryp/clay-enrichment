"""
Tests for Layer 4: email generation worker.

Covers contact grouping, email creation with correct Notion properties,
contact status updates, and batch generation for multiple contacts.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.layers.email_gen import (
    group_contacts_by_company,
    generate_emails_for_company,
    _blocks_to_text,
    _text_to_body_blocks,
    _build_contact_context,
    _build_company_context,
)


# -- Fixtures --


def _make_contact(
    contact_id: str,
    name: str,
    company_id: str,
    campaign_id: str,
    job_title: str = "",
) -> dict:
    """Build a minimal Notion contact page dict."""
    props = {
        "Name": {"title": [{"plain_text": name}]},
        "Job Title": {"rich_text": [{"text": {"content": job_title}, "plain_text": job_title}]},
        "Status": {"select": {"name": "Enriched"}},
        "Company": {"relation": [{"id": company_id}]},
        "Campaign": {"relation": [{"id": campaign_id}]},
    }
    return {"id": contact_id, "properties": props}


def _make_company(
    company_id: str,
    name: str,
    website: str = "",
    industry: str = "Fashion",
) -> dict:
    """Build a minimal Notion company page dict."""
    props = {
        "Name": {"title": [{"plain_text": name}]},
        "Website": {"url": website},
        "Industry": {"select": {"name": industry}},
        "Location": {"rich_text": [{"text": {"content": "Netherlands"}, "plain_text": "Netherlands"}]},
        "Size": {"rich_text": [{"text": {"content": "50-100"}, "plain_text": "50-100"}]},
    }
    return {"id": company_id, "properties": props}


def _make_campaign(campaign_id: str, name: str, target: str) -> dict:
    """Build a minimal Notion campaign page dict."""
    props = {
        "Name": {"title": [{"plain_text": name}]},
        "Target Description": {
            "rich_text": [{"text": {"content": target}, "plain_text": target}],
        },
        "Status": {"select": {"name": "Active"}},
    }
    return {"id": campaign_id, "properties": props}


# -- group_contacts_by_company tests --


def test_group_contacts_single_company():
    """Contacts at the same company are grouped together."""
    contacts = [
        _make_contact("c1", "Alice", "comp-1", "camp-1"),
        _make_contact("c2", "Bob", "comp-1", "camp-1"),
    ]
    result = group_contacts_by_company(contacts)
    assert len(result) == 1
    assert "comp-1" in result
    assert len(result["comp-1"]) == 2


def test_group_contacts_multiple_companies():
    """Contacts at different companies are separated."""
    contacts = [
        _make_contact("c1", "Alice", "comp-1", "camp-1"),
        _make_contact("c2", "Bob", "comp-2", "camp-1"),
        _make_contact("c3", "Carol", "comp-1", "camp-1"),
    ]
    result = group_contacts_by_company(contacts)
    assert len(result) == 2
    assert len(result["comp-1"]) == 2
    assert len(result["comp-2"]) == 1


def test_group_contacts_skips_no_company():
    """Contacts without a company relation are skipped."""
    contact_no_company = {
        "id": "c-orphan",
        "properties": {
            "Name": {"title": [{"plain_text": "Orphan"}]},
            "Company": {"relation": []},
            "Campaign": {"relation": [{"id": "camp-1"}]},
        },
    }
    contacts = [
        _make_contact("c1", "Alice", "comp-1", "camp-1"),
        contact_no_company,
    ]
    result = group_contacts_by_company(contacts)
    assert len(result) == 1
    assert "comp-1" in result


def test_group_contacts_empty_list():
    """Empty input returns empty dict."""
    result = group_contacts_by_company([])
    assert result == {}


# -- Block conversion tests --


def test_blocks_to_text():
    """Paragraph blocks are converted to plain text."""
    blocks = [
        {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"plain_text": "First paragraph."}],
            },
        },
        {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"plain_text": "Second paragraph."}],
            },
        },
    ]
    result = _blocks_to_text(blocks)
    assert "First paragraph." in result
    assert "Second paragraph." in result


def test_blocks_to_text_empty():
    """Empty blocks list returns empty string."""
    assert _blocks_to_text([]) == ""


def test_text_to_body_blocks():
    """Text is split into paragraph blocks on double newlines."""
    text = "Hello Jane,\n\nThis is the body.\n\nMoussa, Avelero"
    blocks = _text_to_body_blocks(text)
    assert len(blocks) == 3
    assert blocks[0]["type"] == "paragraph"
    content = blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]
    assert "Hello Jane," in content


def test_text_to_body_blocks_single_paragraph():
    """Single paragraph produces one block."""
    blocks = _text_to_body_blocks("Just one paragraph here.")
    assert len(blocks) == 1


# -- Context builder tests --


def test_build_contact_context():
    """Contact context includes name, title, and profile."""
    contact = _make_contact("c1", "Jane Smith", "comp-1", "camp-1", job_title="CEO")
    result = _build_contact_context(contact, "Experienced leader in fashion.")
    assert "Jane Smith" in result
    assert "CEO" in result
    assert "Experienced leader" in result


def test_build_contact_context_no_extras():
    """Contact context works with just a name."""
    contact = _make_contact("c1", "Jane Smith", "comp-1", "camp-1")
    result = _build_contact_context(contact, "")
    assert "Jane Smith" in result


def test_build_company_context():
    """Company context includes all available fields."""
    company = _make_company("comp-1", "Filling Pieces", website="https://fillingpieces.com", industry="Fashion")
    result = _build_company_context(company, "Premium sneaker brand from Amsterdam.")
    assert "Filling Pieces" in result
    assert "fillingpieces.com" in result
    assert "Fashion" in result
    assert "Netherlands" in result
    assert "Premium sneaker brand" in result


# -- Email generation integration test --


@pytest.mark.asyncio
async def test_generate_emails_creates_records():
    """Full flow: generates emails and creates Notion records."""
    company = _make_company("comp-1", "TestBrand", website="https://testbrand.com")
    contacts = [
        _make_contact("c1", "Alice Test", "comp-1", "camp-1", job_title="CEO"),
        _make_contact("c2", "Bob Test", "comp-1", "camp-1", job_title="COO"),
    ]
    campaign = _make_campaign("camp-1", "EU DPP Outreach", "Mid-market fashion brands in EU")

    gemini_response = json.dumps([
        {
            "contact_name": "Alice Test",
            "subject": "DPP for TestBrand's EU compliance",
            "body": "Hi Alice,\n\nTestBrand ships to the EU market.\n\nMoussa, Avelero",
        },
        {
            "contact_name": "Bob Test",
            "subject": "Supply chain transparency for TestBrand",
            "body": "Hi Bob,\n\nYour operations role is key.\n\nMoussa, Avelero",
        },
    ])

    config = MagicMock()
    config.model_email_generation = "gemini-2.5-flash"

    gemini_client = MagicMock()
    gemini_client.generate = AsyncMock(return_value={
        "text": gemini_response,
        "input_tokens": 500,
        "output_tokens": 200,
    })

    notion_client = MagicMock()
    notion_client.get_page_body = AsyncMock(return_value=[])

    contacts_db = MagicMock()
    contacts_db.update_contact = AsyncMock(return_value={"id": "c1"})

    emails_db = MagicMock()
    emails_db.create_email = AsyncMock(return_value={"id": "email-1"})

    campaigns_db = MagicMock()
    campaigns_db.db_id = "camp-db-id"
    campaigns_db._client = MagicMock()
    campaigns_db._client.query_database = AsyncMock(return_value=[campaign])

    await generate_emails_for_company(
        company_page=company,
        company_contacts=contacts,
        config=config,
        gemini_client=gemini_client,
        notion_client=notion_client,
        campaigns_db=campaigns_db,
        contacts_db=contacts_db,
        emails_db=emails_db,
    )

    # Two emails created
    assert emails_db.create_email.await_count == 2

    # Check first email was created with correct args
    first_call = emails_db.create_email.call_args_list[0]
    assert first_call.kwargs["subject"] == "DPP for TestBrand's EU compliance"
    assert first_call.kwargs["contact_id"] == "c1"
    assert first_call.kwargs["campaign_id"] == "camp-1"
    assert first_call.kwargs["body_blocks"] is not None

    # Two contacts updated to "Email Generated"
    assert contacts_db.update_contact.await_count == 2
    for call in contacts_db.update_contact.call_args_list:
        props = call.args[1] if len(call.args) > 1 else call.kwargs.get("properties", {})
        assert props["Status"]["select"]["name"] == "Email Generated"


@pytest.mark.asyncio
async def test_generate_emails_handles_json_error():
    """Gracefully handles malformed JSON from Gemini."""
    company = _make_company("comp-1", "BadCo")
    contacts = [_make_contact("c1", "Alice", "comp-1", "camp-1")]

    config = MagicMock()
    config.model_email_generation = "gemini-2.5-flash"

    gemini_client = MagicMock()
    gemini_client.generate = AsyncMock(return_value={
        "text": "not valid json at all",
        "input_tokens": 100,
        "output_tokens": 50,
    })

    notion_client = MagicMock()
    notion_client.get_page_body = AsyncMock(return_value=[])

    contacts_db = MagicMock()
    contacts_db.update_contact = AsyncMock()

    emails_db = MagicMock()
    emails_db.create_email = AsyncMock()

    campaigns_db = MagicMock()
    campaigns_db.db_id = "camp-db-id"
    campaigns_db._client = MagicMock()
    campaigns_db._client.query_database = AsyncMock(return_value=[])

    await generate_emails_for_company(
        company_page=company,
        company_contacts=contacts,
        config=config,
        gemini_client=gemini_client,
        notion_client=notion_client,
        campaigns_db=campaigns_db,
        contacts_db=contacts_db,
        emails_db=emails_db,
    )

    # No emails created when JSON parse fails
    emails_db.create_email.assert_not_awaited()
    contacts_db.update_contact.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_emails_single_contact():
    """Works correctly with a single contact (no batch edge case)."""
    company = _make_company("comp-1", "SoloBrand")
    contacts = [_make_contact("c1", "Solo Person", "comp-1", "camp-1", job_title="Founder")]
    campaign = _make_campaign("camp-1", "Campaign A", "Target solo brands")

    gemini_response = json.dumps([{
        "contact_name": "Solo Person",
        "subject": "DPP for SoloBrand",
        "body": "Hi Solo,\n\nYour brand needs DPP.\n\nMoussa, Avelero",
    }])

    config = MagicMock()
    config.model_email_generation = "gemini-2.5-flash"

    gemini_client = MagicMock()
    gemini_client.generate = AsyncMock(return_value={
        "text": gemini_response,
        "input_tokens": 300,
        "output_tokens": 100,
    })

    notion_client = MagicMock()
    notion_client.get_page_body = AsyncMock(return_value=[])

    contacts_db = MagicMock()
    contacts_db.update_contact = AsyncMock(return_value={"id": "c1"})

    emails_db = MagicMock()
    emails_db.create_email = AsyncMock(return_value={"id": "email-1"})

    campaigns_db = MagicMock()
    campaigns_db.db_id = "camp-db-id"
    campaigns_db._client = MagicMock()
    campaigns_db._client.query_database = AsyncMock(return_value=[campaign])

    await generate_emails_for_company(
        company_page=company,
        company_contacts=contacts,
        config=config,
        gemini_client=gemini_client,
        notion_client=notion_client,
        campaigns_db=campaigns_db,
        contacts_db=contacts_db,
        emails_db=emails_db,
    )

    assert emails_db.create_email.await_count == 1
    assert contacts_db.update_contact.await_count == 1


@pytest.mark.asyncio
async def test_generate_emails_uses_correct_model():
    """Verify the worker uses model_email_generation from config."""
    company = _make_company("comp-1", "ModelTest")
    contacts = [_make_contact("c1", "Tester", "comp-1", "camp-1")]

    config = MagicMock()
    config.model_email_generation = "gemini-2.5-flash"

    gemini_client = MagicMock()
    gemini_client.generate = AsyncMock(return_value={
        "text": json.dumps([{"contact_name": "Tester", "subject": "Test", "body": "Hi"}]),
        "input_tokens": 100,
        "output_tokens": 50,
    })

    notion_client = MagicMock()
    notion_client.get_page_body = AsyncMock(return_value=[])

    contacts_db = MagicMock()
    contacts_db.update_contact = AsyncMock(return_value={"id": "c1"})

    emails_db = MagicMock()
    emails_db.create_email = AsyncMock(return_value={"id": "email-1"})

    campaigns_db = MagicMock()
    campaigns_db.db_id = "camp-db-id"
    campaigns_db._client = MagicMock()
    campaigns_db._client.query_database = AsyncMock(return_value=[])

    await generate_emails_for_company(
        company_page=company,
        company_contacts=contacts,
        config=config,
        gemini_client=gemini_client,
        notion_client=notion_client,
        campaigns_db=campaigns_db,
        contacts_db=contacts_db,
        emails_db=emails_db,
    )

    call_kwargs = gemini_client.generate.call_args.kwargs
    assert call_kwargs["model"] == "gemini-2.5-flash"
    assert call_kwargs["json_mode"] is True


@pytest.mark.asyncio
async def test_email_body_stored_as_page_blocks():
    """Verify email body is stored as page body blocks, not a property."""
    company = _make_company("comp-1", "BlockTest")
    contacts = [_make_contact("c1", "Block Person", "comp-1", "camp-1")]

    body_text = "Hi Block,\n\nParagraph one.\n\nParagraph two.\n\nMoussa, Avelero"
    gemini_response = json.dumps([{
        "contact_name": "Block Person",
        "subject": "Test Subject",
        "body": body_text,
    }])

    config = MagicMock()
    config.model_email_generation = "gemini-2.5-flash"

    gemini_client = MagicMock()
    gemini_client.generate = AsyncMock(return_value={
        "text": gemini_response,
        "input_tokens": 100,
        "output_tokens": 50,
    })

    notion_client = MagicMock()
    notion_client.get_page_body = AsyncMock(return_value=[])

    contacts_db = MagicMock()
    contacts_db.update_contact = AsyncMock(return_value={"id": "c1"})

    emails_db = MagicMock()
    emails_db.create_email = AsyncMock(return_value={"id": "email-1"})

    campaigns_db = MagicMock()
    campaigns_db.db_id = "camp-db-id"
    campaigns_db._client = MagicMock()
    campaigns_db._client.query_database = AsyncMock(return_value=[])

    await generate_emails_for_company(
        company_page=company,
        company_contacts=contacts,
        config=config,
        gemini_client=gemini_client,
        notion_client=notion_client,
        campaigns_db=campaigns_db,
        contacts_db=contacts_db,
        emails_db=emails_db,
    )

    call_kwargs = emails_db.create_email.call_args.kwargs
    body_blocks = call_kwargs["body_blocks"]
    assert len(body_blocks) == 4  # "Hi Block," + para1 + para2 + signoff
    for block in body_blocks:
        assert block["type"] == "paragraph"
        assert "rich_text" in block["paragraph"]
