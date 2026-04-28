"""Tests for the Layer 3 people discovery worker.

Covers the full contact discovery pipeline with mocked external
dependencies: DB, Gemini, Google search, email permutation,
and SMTP verification.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.discovery.contact_finder import ContactFinder, RawContact
from src.discovery.email_permutation import EmailPermutator
from src.discovery.smtp_verify import SMTPVerifier, VerifyResult
from src.layers.people import (
    DBClients,
    _is_duplicate_contact,
    _parse_contacts_with_gemini,
    discover_contacts_for_company,
)
from src.layers.people_helpers import (
    extract_domain as _extract_domain,
    split_name as _split_name,
    verify_email_waterfall as _verify_email_waterfall,
)


def _make_company_page(
    page_id: str = "comp-001",
    name: str = "TestCo",
    website: str = "https://www.testco.com",
    status: str = "Enriched",
) -> dict:
    """Build a minimal flat company dict (Postgres row)."""
    return {
        "id": page_id,
        "name": name,
        "website": website,
        "status": status,
    }


def _make_contact_page(
    page_id: str = "cont-001",
    name: str = "Jane Smith",
) -> dict:
    """Build a minimal flat contact dict (Postgres row)."""
    return {
        "id": page_id,
        "name": name,
    }


def _make_gemini_response(contacts: list[dict]) -> dict:
    """Build a mock Gemini API response containing JSON contact data."""
    return {
        "text": json.dumps(contacts),
        "input_tokens": 100,
        "output_tokens": 50,
    }


def _make_parsed_contact(
    name: str = "Jane Smith",
    title: str = "CEO",
    linkedin_url: str = "https://linkedin.com/in/janesmith",
    relevance_score: int = 9,
) -> dict:
    """Build a parsed contact dict as returned by Gemini."""
    return {
        "name": name,
        "title": title,
        "linkedin_url": linkedin_url,
        "relevance_score": relevance_score,
    }


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------


class TestExtractDomain:
    """Tests for _extract_domain()."""

    def test_full_url(self) -> None:
        assert _extract_domain("https://www.testco.com/about") == "testco.com"

    def test_url_without_www(self) -> None:
        assert _extract_domain("https://testco.com") == "testco.com"

    def test_url_without_scheme(self) -> None:
        assert _extract_domain("www.testco.com") == "testco.com"

    def test_bare_domain(self) -> None:
        assert _extract_domain("testco.com") == "testco.com"

    def test_empty_string(self) -> None:
        assert _extract_domain("") == ""

    def test_whitespace(self) -> None:
        assert _extract_domain("  https://testco.com  ") == "testco.com"

    def test_http_scheme(self) -> None:
        assert _extract_domain("http://testco.com") == "testco.com"

    def test_subdomain_preserved(self) -> None:
        assert _extract_domain("https://shop.testco.com") == "shop.testco.com"


class TestSplitName:
    """Tests for _split_name()."""

    def test_two_parts(self) -> None:
        assert _split_name("Jane Smith") == ("Jane", "Smith")

    def test_three_parts(self) -> None:
        assert _split_name("Jean Claude Van") == ("Jean", "Claude Van")

    def test_single_name(self) -> None:
        assert _split_name("Madonna") == ("Madonna", "")

    def test_empty_string(self) -> None:
        assert _split_name("") == ("", "")

    def test_whitespace(self) -> None:
        assert _split_name("  Jane  Smith  ") == ("Jane", "Smith")


# ---------------------------------------------------------------------------
# Email verification waterfall
# ---------------------------------------------------------------------------


class TestVerifyEmailWaterfall:
    """Tests for _verify_email_waterfall()."""

    def test_stops_at_first_valid(self) -> None:
        """Should stop verifying after the first valid email."""
        verifier = SMTPVerifier()

        call_count = 0
        original_verify = verifier.verify

        async def counting_verify(email: str) -> VerifyResult:
            nonlocal call_count
            call_count += 1
            if email == "jane.smith@testco.com":
                return VerifyResult(email, False, "smtp_rcpt", "high")
            if email == "jane@testco.com":
                return VerifyResult(email, True, "smtp_rcpt", "high")
            return VerifyResult(email, False, "smtp_rcpt", "high")

        with patch.object(verifier, "verify", side_effect=counting_verify):
            email, verified = asyncio.run(
                _verify_email_waterfall(
                    verifier,
                    ["jane.smith@testco.com", "jane@testco.com", "jsmith@testco.com"],
                )
            )

        assert email == "jane@testco.com"
        assert verified is True
        assert call_count == 2  # stopped after second

    def test_returns_first_if_none_verify(self) -> None:
        """Should return first permutation as unverified when none pass."""
        verifier = SMTPVerifier()

        async def always_invalid(email: str) -> VerifyResult:
            return VerifyResult(email, False, "smtp_rcpt", "high")

        with patch.object(verifier, "verify", side_effect=always_invalid):
            email, verified = asyncio.run(
                _verify_email_waterfall(
                    verifier, ["a@x.com", "b@x.com"]
                )
            )

        assert email == "a@x.com"
        assert verified is False

    def test_empty_permutations(self) -> None:
        """Empty permutation list should return empty email, not verified."""
        verifier = SMTPVerifier()
        email, verified = asyncio.run(
            _verify_email_waterfall(verifier, [])
        )
        assert email == ""
        assert verified is False

    def test_exception_during_verify(self) -> None:
        """Should skip emails that raise exceptions and continue."""
        verifier = SMTPVerifier()

        async def flaky_verify(email: str) -> VerifyResult:
            if email == "a@x.com":
                raise ConnectionError("network down")
            return VerifyResult(email, True, "smtp_rcpt", "high")

        with patch.object(verifier, "verify", side_effect=flaky_verify):
            email, verified = asyncio.run(
                _verify_email_waterfall(verifier, ["a@x.com", "b@x.com"])
            )

        assert email == "b@x.com"
        assert verified is True


# ---------------------------------------------------------------------------
# Dedup check
# ---------------------------------------------------------------------------


class TestIsDuplicateContact:
    """Tests for _is_duplicate_contact()."""

    def test_duplicate_found(self) -> None:
        """Should return True when a contact with the same name exists."""
        contacts_db = MagicMock()
        contacts_db.get_contacts_for_company = AsyncMock(
            return_value=[_make_contact_page(name="Jane Smith")]
        )

        result = asyncio.run(
            _is_duplicate_contact(contacts_db, "Jane Smith", "comp-001")
        )
        assert result is True

    def test_duplicate_case_insensitive(self) -> None:
        """Dedup should be case-insensitive."""
        contacts_db = MagicMock()
        contacts_db.get_contacts_for_company = AsyncMock(
            return_value=[_make_contact_page(name="jane smith")]
        )

        result = asyncio.run(
            _is_duplicate_contact(contacts_db, "Jane Smith", "comp-001")
        )
        assert result is True

    def test_no_duplicate(self) -> None:
        """Should return False when no matching contact exists."""
        contacts_db = MagicMock()
        contacts_db.get_contacts_for_company = AsyncMock(
            return_value=[_make_contact_page(name="Bob Jones")]
        )

        result = asyncio.run(
            _is_duplicate_contact(contacts_db, "Jane Smith", "comp-001")
        )
        assert result is False

    def test_empty_contacts(self) -> None:
        """Should return False when company has no existing contacts."""
        contacts_db = MagicMock()
        contacts_db.get_contacts_for_company = AsyncMock(return_value=[])

        result = asyncio.run(
            _is_duplicate_contact(contacts_db, "Jane Smith", "comp-001")
        )
        assert result is False


# ---------------------------------------------------------------------------
# Full contact creation flow
# ---------------------------------------------------------------------------


class TestDiscoverContactsForCompany:
    """Tests for discover_contacts_for_company() with fully mocked deps."""

    def _build_deps(self):
        """Build all mocked dependencies for the discovery function."""
        gemini = MagicMock()
        gemini.generate = AsyncMock(
            return_value=_make_gemini_response([
                _make_parsed_contact("Jane Smith", "CEO"),
            ])
        )

        companies_db = MagicMock()
        companies_db.update_company = AsyncMock(return_value={})
        # Mock pool for campaign lookup in discover_contacts_for_company
        pool_mock = MagicMock()
        pool_mock.fetch = AsyncMock(return_value=[{"campaign_id": "camp-001"}])
        companies_db._pool = pool_mock

        contacts_db = MagicMock()
        contacts_db.get_contacts_for_company = AsyncMock(return_value=[])
        contacts_db.create_contact = AsyncMock(
            return_value={"id": "new-contact-001"}
        )

        db_clients = DBClients(
            companies=companies_db, contacts=contacts_db
        )

        mock_search = MagicMock()
        mock_search.search = AsyncMock(return_value=[])
        contact_finder = ContactFinder(mock_search)
        # Override find_contacts to return controlled data
        contact_finder.find_contacts = AsyncMock(
            return_value=[
                RawContact(
                    name="Jane Smith",
                    title="CEO",
                    source_url="https://linkedin.com/in/jane",
                    linkedin_url="https://linkedin.com/in/jane",
                ),
            ]
        )

        email_permutator = EmailPermutator()

        smtp_verifier = SMTPVerifier()
        smtp_verifier.verify = AsyncMock(
            return_value=VerifyResult(
                "jane.smith@testco.com", True, "smtp_rcpt", "high"
            )
        )

        company = _make_company_page()

        return (
            company, gemini, db_clients,
            contact_finder, email_permutator, smtp_verifier,
        )

    def test_creates_contact_with_verified_email(self) -> None:
        """Full flow should create a contact with a verified email."""
        (
            company, gemini, db_clients,
            contact_finder, email_permutator, smtp_verifier,
        ) = self._build_deps()

        count = asyncio.run(
            discover_contacts_for_company(
                company, gemini, db_clients,
                contact_finder, email_permutator, smtp_verifier,
            )
        )

        assert count == 1
        db_clients.contacts.create_contact.assert_called_once()
        call_kwargs = db_clients.contacts.create_contact.call_args
        assert call_kwargs.kwargs["name"] == "Jane Smith"
        assert call_kwargs.kwargs["email_verified"] is True
        assert call_kwargs.kwargs["company_id"] == "comp-001"
        assert call_kwargs.kwargs["campaign_id"] == "camp-001"

    def test_updates_company_status(self) -> None:
        """Should set company status to 'Contacts Found' after processing."""
        (
            company, gemini, db_clients,
            contact_finder, email_permutator, smtp_verifier,
        ) = self._build_deps()

        asyncio.run(
            discover_contacts_for_company(
                company, gemini, db_clients,
                contact_finder, email_permutator, smtp_verifier,
            )
        )

        db_clients.companies.update_company.assert_called_once()
        update_args = db_clients.companies.update_company.call_args
        assert update_args.args[0] == "comp-001"
        props = update_args.args[1]
        assert props["status"] == "Contacts Found"

    def test_skips_duplicate_contacts(self) -> None:
        """Contacts already in DB for this company should be skipped."""
        (
            company, gemini, db_clients,
            contact_finder, email_permutator, smtp_verifier,
        ) = self._build_deps()

        # Pre-populate with existing contact
        db_clients.contacts.get_contacts_for_company = AsyncMock(
            return_value=[_make_contact_page(name="Jane Smith")]
        )

        count = asyncio.run(
            discover_contacts_for_company(
                company, gemini, db_clients,
                contact_finder, email_permutator, smtp_verifier,
            )
        )

        assert count == 0
        db_clients.contacts.create_contact.assert_not_called()

    def test_unverified_contact_still_created(self) -> None:
        """Contact should still be created if no email verifies."""
        (
            company, gemini, db_clients,
            contact_finder, email_permutator, smtp_verifier,
        ) = self._build_deps()

        # All emails fail verification
        smtp_verifier.verify = AsyncMock(
            return_value=VerifyResult(
                "jane.smith@testco.com", False, "smtp_rcpt", "high"
            )
        )

        count = asyncio.run(
            discover_contacts_for_company(
                company, gemini, db_clients,
                contact_finder, email_permutator, smtp_verifier,
            )
        )

        assert count == 1
        call_kwargs = db_clients.contacts.create_contact.call_args
        assert call_kwargs.kwargs["email_verified"] is False
        # Should still have an email (best guess)
        assert call_kwargs.kwargs["email_addr"] != ""

    def test_no_contacts_found(self) -> None:
        """Should handle zero contacts gracefully."""
        (
            company, gemini, db_clients,
            contact_finder, email_permutator, smtp_verifier,
        ) = self._build_deps()

        contact_finder.find_contacts = AsyncMock(return_value=[])
        gemini.generate = AsyncMock(
            return_value=_make_gemini_response([])
        )

        count = asyncio.run(
            discover_contacts_for_company(
                company, gemini, db_clients,
                contact_finder, email_permutator, smtp_verifier,
            )
        )

        assert count == 0
        db_clients.contacts.create_contact.assert_not_called()
        # Status should still be updated
        db_clients.companies.update_company.assert_called_once()

    def test_error_recovery_per_contact(self) -> None:
        """Error on one contact should not prevent processing others."""
        (
            company, gemini, db_clients,
            contact_finder, email_permutator, smtp_verifier,
        ) = self._build_deps()

        # Return two contacts
        gemini.generate = AsyncMock(
            return_value=_make_gemini_response([
                _make_parsed_contact("Bad Contact", "CTO"),
                _make_parsed_contact("Good Contact", "CEO"),
            ])
        )

        contact_finder.find_contacts = AsyncMock(
            return_value=[
                RawContact("Bad Contact", "CTO", "https://example.com", None),
                RawContact("Good Contact", "CEO", "https://example.com", None),
            ]
        )

        # First contact creation fails, second succeeds
        call_count = 0

        async def create_with_failure(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs["name"] == "Bad Contact":
                raise RuntimeError("DB error")
            return {"id": "new-contact-002"}

        db_clients.contacts.create_contact = AsyncMock(
            side_effect=create_with_failure
        )

        count = asyncio.run(
            discover_contacts_for_company(
                company, gemini, db_clients,
                contact_finder, email_permutator, smtp_verifier,
            )
        )

        # Only the good contact should count
        assert count == 1
        # Company status should still be updated despite the error
        db_clients.companies.update_company.assert_called_once()

    def test_no_domain_skips_email(self) -> None:
        """Company without a website should skip email generation."""
        (
            company, gemini, db_clients,
            contact_finder, email_permutator, smtp_verifier,
        ) = self._build_deps()

        # Company with no website
        company["website"] = ""

        count = asyncio.run(
            discover_contacts_for_company(
                company, gemini, db_clients,
                contact_finder, email_permutator, smtp_verifier,
            )
        )

        assert count == 1
        call_kwargs = db_clients.contacts.create_contact.call_args
        # No email should be set since no domain available
        assert call_kwargs.kwargs["email_addr"] == ""
        assert call_kwargs.kwargs["email_verified"] is False
        # SMTP verifier should not have been called
        smtp_verifier.verify.assert_not_called()

    def test_contact_with_linkedin_url(self) -> None:
        """LinkedIn URL from Gemini parsing should be passed to the DB layer."""
        (
            company, gemini, db_clients,
            contact_finder, email_permutator, smtp_verifier,
        ) = self._build_deps()

        gemini.generate = AsyncMock(
            return_value=_make_gemini_response([
                _make_parsed_contact(
                    "Jane Smith", "CEO",
                    linkedin_url="https://linkedin.com/in/janesmith",
                ),
            ])
        )

        asyncio.run(
            discover_contacts_for_company(
                company, gemini, db_clients,
                contact_finder, email_permutator, smtp_verifier,
            )
        )

        call_kwargs = db_clients.contacts.create_contact.call_args
        assert call_kwargs.kwargs["linkedin_url"] == "https://linkedin.com/in/janesmith"
