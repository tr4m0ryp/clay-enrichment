"""
Tests for Layer 4: email generation helpers.

Covers the low-level text/block conversion and context-building
helpers in src.layers.email_context. The higher-level
generate_emails_for_company flow is tested via manual integration runs
because its signature takes junction entries and depends on multiple
mocked Notion endpoints which would require extensive fixture wiring.
"""

from src.layers.email_context import (
    blocks_to_text,
    text_to_body_blocks,
    build_contact_context,
    build_company_context,
    group_junction_entries_by_company,
    entry_has_email_subject,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_contact(
    contact_id: str,
    name: str,
    company_id: str,
    campaign_id: str,
    job_title: str = "",
    context: str = "",
) -> dict:
    """Build a minimal Notion contact page dict."""
    props = {
        "Name": {"title": [{"plain_text": name}]},
        "Job Title": {
            "rich_text": [{"text": {"content": job_title}, "plain_text": job_title}]
        },
        "Context": {
            "rich_text": [{"text": {"content": context}, "plain_text": context}]
        },
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
        "Location": {
            "rich_text": [
                {"text": {"content": "Netherlands"}, "plain_text": "Netherlands"}
            ]
        },
        "Size": {
            "rich_text": [{"text": {"content": "50-100"}, "plain_text": "50-100"}]
        },
    }
    return {"id": company_id, "properties": props}


def _make_junction_entry(
    entry_id: str,
    contact_id: str,
    campaign_id: str,
    company_id: str = "",
    email_subject: str = "",
) -> dict:
    """Build a minimal junction page dict."""
    props: dict = {
        "Contact": {"relation": [{"id": contact_id}]},
        "Campaign": {"relation": [{"id": campaign_id}]},
        "Email Subject": {
            "rich_text": [
                {"text": {"content": email_subject}, "plain_text": email_subject}
            ]
        },
    }
    if company_id:
        props["Company"] = {"relation": [{"id": company_id}]}
    else:
        props["Company"] = {"relation": []}
    return {"id": entry_id, "properties": props}


# ---------------------------------------------------------------------------
# group_junction_entries_by_company tests
# ---------------------------------------------------------------------------


def test_group_junction_entries_single_company():
    """Entries at the same company are grouped together."""
    entries = [
        _make_junction_entry("j1", "c1", "camp-1", company_id="comp-1"),
        _make_junction_entry("j2", "c2", "camp-1", company_id="comp-1"),
    ]
    result = group_junction_entries_by_company(entries)
    assert len(result) == 1
    assert "comp-1" in result
    assert len(result["comp-1"]) == 2


def test_group_junction_entries_multiple_companies():
    """Entries at different companies are separated."""
    entries = [
        _make_junction_entry("j1", "c1", "camp-1", company_id="comp-1"),
        _make_junction_entry("j2", "c2", "camp-1", company_id="comp-2"),
        _make_junction_entry("j3", "c3", "camp-1", company_id="comp-1"),
    ]
    result = group_junction_entries_by_company(entries)
    assert len(result) == 2
    assert len(result["comp-1"]) == 2
    assert len(result["comp-2"]) == 1


def test_group_junction_entries_skips_no_company():
    """Entries without a company relation are skipped."""
    entries = [
        _make_junction_entry("j1", "c1", "camp-1", company_id="comp-1"),
        _make_junction_entry("j-orphan", "c2", "camp-1", company_id=""),
    ]
    result = group_junction_entries_by_company(entries)
    assert len(result) == 1
    assert "comp-1" in result


def test_group_junction_entries_empty_list():
    """Empty input returns empty dict."""
    result = group_junction_entries_by_company([])
    assert result == {}


# ---------------------------------------------------------------------------
# entry_has_email_subject tests
# ---------------------------------------------------------------------------


def test_entry_has_email_subject_true():
    """Returns True when Email Subject is set."""
    entry = _make_junction_entry(
        "j1", "c1", "camp-1", email_subject="Outreach to Alice"
    )
    assert entry_has_email_subject(entry) is True


def test_entry_has_email_subject_false():
    """Returns False when Email Subject is empty."""
    entry = _make_junction_entry("j1", "c1", "camp-1", email_subject="")
    assert entry_has_email_subject(entry) is False


def test_entry_has_email_subject_whitespace_only():
    """Returns False when Email Subject is only whitespace."""
    entry = _make_junction_entry("j1", "c1", "camp-1", email_subject="   ")
    assert entry_has_email_subject(entry) is False


# ---------------------------------------------------------------------------
# Block conversion tests
# ---------------------------------------------------------------------------


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
    result = blocks_to_text(blocks)
    assert "First paragraph." in result
    assert "Second paragraph." in result


def test_blocks_to_text_empty():
    """Empty blocks list returns empty string."""
    assert blocks_to_text([]) == ""


def test_text_to_body_blocks():
    """Text is split into paragraph blocks on double newlines."""
    text = "Hello Jane,\n\nThis is the body.\n\nMoussa, Avelero"
    blocks = text_to_body_blocks(text)
    assert len(blocks) == 3
    assert blocks[0]["type"] == "paragraph"
    content = blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]
    assert "Hello Jane," in content


def test_text_to_body_blocks_single_paragraph():
    """Single paragraph produces one block."""
    blocks = text_to_body_blocks("Just one paragraph here.")
    assert len(blocks) == 1


def test_text_to_body_blocks_empty_string():
    """Empty string produces no blocks."""
    blocks = text_to_body_blocks("")
    assert len(blocks) == 0


# ---------------------------------------------------------------------------
# Context builder tests
# ---------------------------------------------------------------------------


def test_build_contact_context():
    """Contact context includes name, title, and person research."""
    contact = _make_contact(
        "c1", "Jane Smith", "comp-1", "camp-1", job_title="CEO"
    )
    result = build_contact_context(contact, "Experienced leader in fashion.")
    assert "Jane Smith" in result
    assert "CEO" in result
    assert "Experienced leader" in result


def test_build_contact_context_no_extras():
    """Contact context works with just a name."""
    contact = _make_contact("c1", "Jane Smith", "comp-1", "camp-1")
    result = build_contact_context(contact, "")
    assert "Jane Smith" in result


def test_build_contact_context_with_context_property():
    """Context property is included in output."""
    contact = _make_contact(
        "c1", "Jane Smith", "comp-1", "camp-1",
        job_title="CEO", context="Co-founder, focuses on sustainability.",
    )
    result = build_contact_context(contact, "")
    assert "Jane Smith" in result
    assert "Co-founder" in result


def test_build_company_context():
    """Company context includes all available fields."""
    company = _make_company(
        "comp-1", "Filling Pieces",
        website="https://fillingpieces.com", industry="Fashion",
    )
    result = build_company_context(
        company, "Premium sneaker brand from Amsterdam."
    )
    assert "Filling Pieces" in result
    assert "fillingpieces.com" in result
    assert "Fashion" in result
    assert "Netherlands" in result
    assert "Premium sneaker brand" in result


def test_build_company_context_no_body():
    """Company context works with empty body."""
    company = _make_company("comp-1", "MinimalCo")
    result = build_company_context(company, "")
    assert "MinimalCo" in result
