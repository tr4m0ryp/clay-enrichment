"""
Tests for Layer 4: email generation helpers.

Covers the low-level context-building helpers in src.layers.email_context.
The higher-level generate_emails_for_company flow is tested via manual
integration runs because its signature depends on DB instances.
"""

from src.layers.email_context import (
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
    job_title: str = "",
    context: str = "",
) -> dict:
    """Build a minimal flat contact dict (Postgres row)."""
    return {
        "id": contact_id,
        "name": name,
        "job_title": job_title,
        "context": context,
        "status": "Enriched",
        "company_id": company_id,
    }


def _make_company(
    company_id: str,
    name: str,
    website: str = "",
    industry: str = "Fashion",
    location: str = "",
    size: str = "",
) -> dict:
    """Build a minimal flat company dict (Postgres row)."""
    return {
        "id": company_id,
        "name": name,
        "website": website,
        "industry": industry,
        "location": location,
        "size": size,
    }


def _make_junction_entry(
    entry_id: str,
    contact_id: str,
    campaign_id: str,
    company_id: str = "",
    email_subject: str = "",
) -> dict:
    """Build a minimal flat junction entry dict (Postgres row)."""
    return {
        "id": entry_id,
        "contact_id": contact_id or None,
        "campaign_id": campaign_id,
        "company_id": company_id or None,
        "email_subject": email_subject,
    }


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
    """Entries without a company_id are skipped."""
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
    """Returns True when email_subject is set."""
    entry = _make_junction_entry(
        "j1", "c1", "camp-1", email_subject="Outreach to Alice"
    )
    assert entry_has_email_subject(entry) is True


def test_entry_has_email_subject_false():
    """Returns False when email_subject is empty."""
    entry = _make_junction_entry("j1", "c1", "camp-1", email_subject="")
    assert entry_has_email_subject(entry) is False


def test_entry_has_email_subject_whitespace_only():
    """Returns False when email_subject is only whitespace."""
    entry = _make_junction_entry("j1", "c1", "camp-1", email_subject="   ")
    assert entry_has_email_subject(entry) is False


# ---------------------------------------------------------------------------
# Context builder tests
# ---------------------------------------------------------------------------


def test_build_contact_context():
    """Contact context includes name, title, and person research."""
    contact = _make_contact(
        "c1", "Jane Smith", "comp-1", job_title="CEO"
    )
    result = build_contact_context(contact, "Experienced leader in fashion.")
    assert "Jane Smith" in result
    assert "CEO" in result
    assert "Experienced leader" in result


def test_build_contact_context_no_extras():
    """Contact context works with just a name."""
    contact = _make_contact("c1", "Jane Smith", "comp-1")
    result = build_contact_context(contact, "")
    assert "Jane Smith" in result


def test_build_contact_context_with_context_property():
    """Context field is included in output."""
    contact = _make_contact(
        "c1", "Jane Smith", "comp-1",
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
        location="Netherlands", size="50-100",
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
