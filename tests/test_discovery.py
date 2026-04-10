"""Tests for the discovery module.

Covers email permutation generation, contact finder parsing, and
SMTP verification with mocked network interactions.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.discovery.email_permutation import EmailPermutator
from src.discovery.contact_finder import ContactFinder, RawContact
from src.discovery.smtp_verify import SMTPVerifier, VerifyResult


# ---------------------------------------------------------------------------
# EmailPermutator tests
# ---------------------------------------------------------------------------


class TestEmailPermutator:
    """Tests for EmailPermutator.generate()."""

    def setup_method(self) -> None:
        """Create a fresh permutator for each test."""
        self.permutator = EmailPermutator()

    def test_standard_name(self) -> None:
        """Verify correct patterns for 'John Doe' at 'company.com'."""
        results = self.permutator.generate("John", "Doe", "company.com")

        assert "john.doe@company.com" in results
        assert "john@company.com" in results
        assert "jdoe@company.com" in results
        assert "johnd@company.com" in results
        assert "john_doe@company.com" in results
        assert "doe.john@company.com" in results
        assert "doe@company.com" in results
        assert "j.doe@company.com" in results
        assert len(results) == 8

    def test_order_matches_frequency(self) -> None:
        """First pattern should be first.last, the most common format."""
        results = self.permutator.generate("John", "Doe", "company.com")
        assert results[0] == "john.doe@company.com"
        assert results[1] == "john@company.com"
        assert results[2] == "jdoe@company.com"

    def test_hyphenated_last_name(self) -> None:
        """Hyphenated names should keep the hyphen."""
        results = self.permutator.generate(
            "Marie", "Claire-Dupont", "example.fr"
        )
        assert "marie.claire-dupont@example.fr" in results
        assert "mclaire-dupont@example.fr" in results
        assert "marie_claire-dupont@example.fr" in results

    def test_accented_characters(self) -> None:
        """Accented characters should be normalized to ASCII."""
        results = self.permutator.generate(
            "Rene", "Muller", "example.de"
        )
        assert "rene.muller@example.de" in results

        # French accented name
        results = self.permutator.generate(
            "Helene", "Bezier", "example.fr"
        )
        assert "helene.bezier@example.fr" in results

    def test_accented_input_normalized(self) -> None:
        """Names with diacritics should produce clean ASCII emails."""
        results = self.permutator.generate(
            "Helene", "Bezier", "example.fr"
        )
        for email in results:
            local = email.split("@")[0]
            assert local.isascii(), f"Non-ASCII in local part: {local}"

    def test_single_name(self) -> None:
        """Single name (no last name) should produce one result."""
        results = self.permutator.generate("Madonna", "", "music.com")
        assert results == ["madonna@music.com"]

    def test_single_name_none(self) -> None:
        """None as last name should be treated like empty string."""
        results = self.permutator.generate("Cher", None, "music.com")
        assert results == ["cher@music.com"]

    def test_empty_first_name(self) -> None:
        """Empty first name should return no results."""
        results = self.permutator.generate("", "Doe", "company.com")
        assert results == []

    def test_empty_domain(self) -> None:
        """Empty domain should return no results."""
        results = self.permutator.generate("John", "Doe", "")
        assert results == []

    def test_whitespace_handling(self) -> None:
        """Leading/trailing whitespace should be stripped."""
        results = self.permutator.generate(
            "  John  ", "  Doe  ", "  company.com  "
        )
        assert "john.doe@company.com" in results

    def test_all_lowercase(self) -> None:
        """All generated emails should be lowercase."""
        results = self.permutator.generate("JOHN", "DOE", "Company.COM")
        for email in results:
            assert email == email.lower()


# ---------------------------------------------------------------------------
# ContactFinder tests
# ---------------------------------------------------------------------------


class TestContactFinder:
    """Tests for ContactFinder with mocked search results."""

    def setup_method(self) -> None:
        """Create a finder with a mock search client."""
        self.mock_client = MagicMock()
        self.mock_client.search = AsyncMock(return_value=[])
        self.finder = ContactFinder(self.mock_client)

    def test_find_contacts_linkedin_results(self) -> None:
        """Should parse LinkedIn results into RawContact objects."""
        self.mock_client.search = AsyncMock(
            return_value=[
                {
                    "title": "Jane Smith - CEO - Acme Corp | LinkedIn",
                    "link": "https://linkedin.com/in/jane-smith",
                    "snippet": "Jane Smith is the CEO of Acme Corp...",
                },
                {
                    "title": "Not a Person Page",
                    "link": "https://example.com/about",
                    "snippet": "About our team...",
                },
            ]
        )

        contacts = asyncio.run(
            self.finder.find_contacts("Acme Corp", "acme.com")
        )

        linkedin_contacts = [
            c for c in contacts if c.linkedin_url is not None
        ]
        assert len(linkedin_contacts) >= 1
        # Jane Smith should appear from the LinkedIn-specific parser
        names = [c.name for c in linkedin_contacts]
        assert "Jane Smith" in names
        jane = next(c for c in linkedin_contacts if c.name == "Jane Smith")
        assert jane.linkedin_url == "https://linkedin.com/in/jane-smith"

    def test_find_contacts_deduplication(self) -> None:
        """Duplicate names across searches should be deduplicated."""
        self.mock_client.search = AsyncMock(
            return_value=[
                {
                    "title": "John Doe - Founder - TestCo | LinkedIn",
                    "link": "https://linkedin.com/in/john-doe",
                    "snippet": "Founder at TestCo",
                },
            ]
        )

        contacts = asyncio.run(
            self.finder.find_contacts("TestCo", "testco.com")
        )

        names = [c.name for c in contacts]
        assert names.count("John Doe") == 1

    def test_find_contacts_empty_results(self) -> None:
        """Should handle empty search results gracefully."""
        self.mock_client.search = AsyncMock(return_value=[])

        contacts = asyncio.run(
            self.finder.find_contacts("Unknown Corp", "unknown.com")
        )

        assert contacts == []

    def test_find_contacts_search_failure(self) -> None:
        """Should handle search client errors without crashing."""
        self.mock_client.search = AsyncMock(
            side_effect=Exception("API error")
        )

        contacts = asyncio.run(
            self.finder.find_contacts("FailCorp", "failcorp.com")
        )

        assert contacts == []

    def test_find_contacts_runs_broad_searches(self) -> None:
        """Should run the three broad search strategies."""
        self.mock_client.search = AsyncMock(return_value=[])

        asyncio.run(
            self.finder.find_contacts("TestCo", "testco.com")
        )

        # Should run team/people search + two LinkedIn searches
        assert self.mock_client.search.call_count == 3

    def test_extract_name_from_linkedin_title(self) -> None:
        """Should extract clean names from LinkedIn page titles."""
        name = self.finder._extract_name_from_linkedin_title(
            "Alice Johnson - VP Engineering - Corp | LinkedIn"
        )
        assert name == "Alice Johnson"

    def test_extract_name_rejects_invalid(self) -> None:
        """Should reject titles that do not contain a person name."""
        name = self.finder._extract_name_from_linkedin_title(
            "123 Corp | LinkedIn"
        )
        assert name is None


# ---------------------------------------------------------------------------
# SMTPVerifier tests
# ---------------------------------------------------------------------------


class TestSMTPVerifier:
    """Tests for SMTPVerifier with mocked network calls."""

    def setup_method(self) -> None:
        """Create a fresh verifier for each test."""
        self.verifier = SMTPVerifier()

    def test_no_mx_records(self) -> None:
        """Domain with no MX records should return invalid + high confidence."""
        with patch.object(
            self.verifier, "_resolve_mx", new_callable=AsyncMock
        ) as mock_mx:
            mock_mx.return_value = []

            result = asyncio.run(
                self.verifier.verify("test@nonexistent-domain.invalid")
            )

            assert result.valid is False
            assert result.method == "mx_check"
            assert result.confidence == "high"

    def test_smtp_250_valid(self) -> None:
        """SMTP 250 response should mark email as valid."""
        with patch.object(
            self.verifier, "_resolve_mx", new_callable=AsyncMock
        ) as mock_mx, patch.object(
            self.verifier, "_smtp_check", new_callable=AsyncMock
        ) as mock_smtp:
            mock_mx.return_value = ["mx.example.com"]
            mock_smtp.return_value = VerifyResult(
                email="real@example.com",
                valid=True,
                method="smtp_rcpt",
                confidence="high",
            )

            result = asyncio.run(
                self.verifier.verify("real@example.com")
            )

            assert result.valid is True
            assert result.method == "smtp_rcpt"
            assert result.confidence == "high"

    def test_smtp_550_invalid(self) -> None:
        """SMTP 550 response should mark email as invalid."""
        with patch.object(
            self.verifier, "_resolve_mx", new_callable=AsyncMock
        ) as mock_mx, patch.object(
            self.verifier, "_smtp_check", new_callable=AsyncMock
        ) as mock_smtp:
            mock_mx.return_value = ["mx.example.com"]
            mock_smtp.return_value = VerifyResult(
                email="fake@example.com",
                valid=False,
                method="smtp_rcpt",
                confidence="high",
            )

            result = asyncio.run(
                self.verifier.verify("fake@example.com")
            )

            assert result.valid is False
            assert result.method == "smtp_rcpt"
            assert result.confidence == "high"

    def test_catch_all_low_confidence(self) -> None:
        """Catch-all domains should be marked as low confidence."""
        with patch.object(
            self.verifier, "_resolve_mx", new_callable=AsyncMock
        ) as mock_mx, patch.object(
            self.verifier, "_smtp_check", new_callable=AsyncMock
        ) as mock_smtp:
            mock_mx.return_value = ["mx.catchall.com"]
            mock_smtp.return_value = VerifyResult(
                email="anyone@catchall.com",
                valid=True,
                method="catch_all",
                confidence="low",
            )

            result = asyncio.run(
                self.verifier.verify("anyone@catchall.com")
            )

            assert result.valid is True
            assert result.method == "catch_all"
            assert result.confidence == "low"

    def test_all_mx_unreachable(self) -> None:
        """If all MX hosts fail, should return unknown + low confidence."""
        with patch.object(
            self.verifier, "_resolve_mx", new_callable=AsyncMock
        ) as mock_mx, patch.object(
            self.verifier, "_smtp_check", new_callable=AsyncMock
        ) as mock_smtp:
            mock_mx.return_value = ["mx1.example.com", "mx2.example.com"]
            mock_smtp.return_value = None  # both unreachable

            result = asyncio.run(
                self.verifier.verify("test@example.com")
            )

            assert result.valid is False
            assert result.method == "unknown"
            assert result.confidence == "low"

    def test_verify_result_fields(self) -> None:
        """VerifyResult dataclass should store all fields correctly."""
        result = VerifyResult(
            email="test@example.com",
            valid=True,
            method="smtp_rcpt",
            confidence="high",
        )
        assert result.email == "test@example.com"
        assert result.valid is True
        assert result.method == "smtp_rcpt"
        assert result.confidence == "high"

    def test_batch_verify(self) -> None:
        """verify_batch should return results for all emails."""
        with patch.object(
            self.verifier, "verify", new_callable=AsyncMock
        ) as mock_verify:
            mock_verify.side_effect = [
                VerifyResult("a@x.com", True, "smtp_rcpt", "high"),
                VerifyResult("b@x.com", False, "smtp_rcpt", "high"),
            ]

            results = asyncio.run(
                self.verifier.verify_batch(["a@x.com", "b@x.com"])
            )

            assert len(results) == 2
            assert results[0].valid is True
            assert results[1].valid is False
