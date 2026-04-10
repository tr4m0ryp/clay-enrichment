"""
Tests for Notion property builder and extractor helpers.

These are pure unit tests with no mocking needed -- they verify
that dict construction and parsing works correctly.
"""

from datetime import datetime, timezone

import pytest

from src.notion.prop_helpers import (
    title_prop,
    rich_text_prop,
    select_prop,
    number_prop,
    url_prop,
    email_prop,
    checkbox_prop,
    date_prop,
    relation_prop,
    extract_title,
    extract_rich_text,
    extract_select,
    extract_number,
    extract_url,
    extract_email,
    extract_checkbox,
    extract_date,
    extract_relation_ids,
)


class TestPropertyBuilders:
    """Test that property builder functions produce correct Notion API dicts."""

    def test_title_prop(self):
        result = title_prop("Hello")
        assert result == {"title": [{"text": {"content": "Hello"}}]}

    def test_title_prop_truncation(self):
        long_text = "x" * 3000
        result = title_prop(long_text)
        assert len(result["title"][0]["text"]["content"]) == 2000

    def test_rich_text_prop(self):
        result = rich_text_prop("Some description")
        assert result == {"rich_text": [{"text": {"content": "Some description"}}]}

    def test_rich_text_prop_truncation(self):
        long_text = "y" * 3000
        result = rich_text_prop(long_text)
        assert len(result["rich_text"][0]["text"]["content"]) == 2000

    def test_select_prop(self):
        assert select_prop("Active") == {"select": {"name": "Active"}}

    def test_number_prop(self):
        assert number_prop(42) == {"number": 42}
        assert number_prop(3.14) == {"number": 3.14}

    def test_url_prop(self):
        assert url_prop("https://example.com") == {"url": "https://example.com"}

    def test_email_prop(self):
        assert email_prop("a@b.com") == {"email": "a@b.com"}

    def test_checkbox_prop(self):
        assert checkbox_prop(True) == {"checkbox": True}
        assert checkbox_prop(False) == {"checkbox": False}

    def test_date_prop_with_string(self):
        result = date_prop("2025-01-15")
        assert result == {"date": {"start": "2025-01-15"}}

    def test_date_prop_with_datetime(self):
        dt = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = date_prop(dt)
        assert result["date"]["start"].startswith("2025-06-01")

    def test_date_prop_default_now(self):
        result = date_prop()
        assert "date" in result
        assert "start" in result["date"]

    def test_relation_prop(self):
        result = relation_prop(["id-1", "id-2"])
        assert result == {"relation": [{"id": "id-1"}, {"id": "id-2"}]}

    def test_relation_prop_empty(self):
        result = relation_prop([])
        assert result == {"relation": []}


class TestPropertyExtractors:
    """Test that property extraction functions parse Notion page dicts."""

    def _make_page(self, properties: dict) -> dict:
        return {"properties": properties}

    def test_extract_title(self):
        page = self._make_page({
            "Name": {"title": [{"plain_text": "Acme Corp"}]}
        })
        assert extract_title(page, "Name") == "Acme Corp"

    def test_extract_title_empty(self):
        page = self._make_page({"Name": {"title": []}})
        assert extract_title(page, "Name") == ""

    def test_extract_title_missing(self):
        page = self._make_page({})
        assert extract_title(page, "Name") == ""

    def test_extract_rich_text(self):
        page = self._make_page({
            "Desc": {"rich_text": [
                {"plain_text": "Hello "},
                {"plain_text": "world"},
            ]}
        })
        assert extract_rich_text(page, "Desc") == "Hello world"

    def test_extract_select(self):
        page = self._make_page({"Status": {"select": {"name": "Active"}}})
        assert extract_select(page, "Status") == "Active"

    def test_extract_select_none(self):
        page = self._make_page({"Status": {"select": None}})
        assert extract_select(page, "Status") == ""

    def test_extract_number(self):
        page = self._make_page({"Score": {"number": 85}})
        assert extract_number(page, "Score") == 85

    def test_extract_number_none(self):
        page = self._make_page({"Score": {"number": None}})
        assert extract_number(page, "Score") is None

    def test_extract_url(self):
        page = self._make_page({"Website": {"url": "https://example.com"}})
        assert extract_url(page, "Website") == "https://example.com"

    def test_extract_url_none(self):
        page = self._make_page({"Website": {"url": None}})
        assert extract_url(page, "Website") == ""

    def test_extract_email(self):
        page = self._make_page({"Email": {"email": "a@b.com"}})
        assert extract_email(page, "Email") == "a@b.com"

    def test_extract_checkbox(self):
        page = self._make_page({"Verified": {"checkbox": True}})
        assert extract_checkbox(page, "Verified") is True

    def test_extract_checkbox_default(self):
        page = self._make_page({})
        assert extract_checkbox(page, "Verified") is False

    def test_extract_date(self):
        page = self._make_page({"Created": {"date": {"start": "2025-01-15"}}})
        assert extract_date(page, "Created") == "2025-01-15"

    def test_extract_date_none(self):
        page = self._make_page({"Created": {"date": None}})
        assert extract_date(page, "Created") == ""

    def test_extract_relation_ids(self):
        page = self._make_page({
            "Campaign": {"relation": [{"id": "abc"}, {"id": "def"}]}
        })
        assert extract_relation_ids(page, "Campaign") == ["abc", "def"]

    def test_extract_relation_ids_empty(self):
        page = self._make_page({"Campaign": {"relation": []}})
        assert extract_relation_ids(page, "Campaign") == []
