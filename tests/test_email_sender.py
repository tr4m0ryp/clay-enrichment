"""
Tests for the email sending engine.

Covers SenderPool rotation and limits, randomized delays, fail-rate
threshold, business hours check, and graceful SMTP-disabled behavior.
All SMTP calls are mocked.
"""

import asyncio
import smtplib
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import SenderAccount, Config
from src.email.pool import (
    SenderPool,
    compute_delay as _compute_delay,
    blocks_to_plain_text as _blocks_to_plain_text,
    is_business_hours,
)
from src.email.sender import (
    send_batch,
    email_sender_worker,
)


# -- Fixtures --


def _make_senders(count: int = 3) -> list[SenderAccount]:
    """Create a list of test sender accounts."""
    return [
        SenderAccount(email=f"sender{i}@test.com", password=f"pass{i}")
        for i in range(1, count + 1)
    ]


def _make_config(**overrides) -> Config:
    """Create a Config with sensible test defaults."""
    defaults = {
        "smtp_host": "smtp.test.com",
        "smtp_port": 587,
        "senders": _make_senders(2),
        "email_daily_limit": 10,
        "email_min_delay": 1,
        "email_max_delay": 2,
    }
    defaults.update(overrides)
    return Config(**defaults)


def _make_email_page(
    page_id: str,
    subject: str,
    contact_id: str = "contact-1",
    campaign_id: str = "campaign-1",
) -> dict:
    """Build a minimal Notion email page dict for testing."""
    return {
        "id": page_id,
        "properties": {
            "Subject": {"title": [{"plain_text": subject}]},
            "Contact": {"relation": [{"id": contact_id}]},
            "Campaign": {"relation": [{"id": campaign_id}]},
            "Status": {"select": {"name": "Approved"}},
        },
    }


def _make_notion_clients(
    approved: list[dict] | None = None,
    recipient_email: str = "recipient@example.com",
    body_blocks: list[dict] | None = None,
    campaign_status: str = "Active",
) -> MagicMock:
    """Build a mock notion_clients object with emails, contacts, campaigns."""
    mock = MagicMock()

    # emails DB
    emails_db = MagicMock()
    emails_db.get_approved_emails = AsyncMock(
        return_value=approved or []
    )
    emails_db._client = MagicMock()
    emails_db._client.update_page = AsyncMock(return_value={"id": "x"})
    emails_db._client.get_page_body = AsyncMock(
        return_value=body_blocks or [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "Hello, this is a test."}]
                },
            }
        ]
    )
    mock.emails = emails_db

    # contacts DB -- _client is used to retrieve contact page
    contacts_db = MagicMock()
    contacts_db._client = MagicMock()
    contacts_db._client._sdk = MagicMock()
    contacts_db._client._sdk.pages = MagicMock()
    contacts_db._client._sdk.pages.retrieve = MagicMock(
        return_value={
            "id": "contact-1",
            "properties": {
                "Email": {"email": recipient_email},
            },
        }
    )
    contacts_db._client._call = AsyncMock(
        return_value={
            "id": "contact-1",
            "properties": {
                "Email": {"email": recipient_email},
            },
        }
    )
    mock.contacts = contacts_db

    # campaigns DB -- returns a campaign with the given status
    campaigns_db = MagicMock()
    campaigns_db._client = MagicMock()
    campaigns_db._client._sdk = MagicMock()
    campaigns_db._client._sdk.pages = MagicMock()
    campaigns_db._client._call = AsyncMock(
        return_value={
            "id": "campaign-1",
            "properties": {
                "Status": {"select": {"name": campaign_status}},
            },
        }
    )
    mock.campaigns = campaigns_db

    # contact_campaigns junction -- not used by most tests; disable via None
    mock.contact_campaigns = None

    return mock


# -- SenderPool tests --


class TestSenderPool:
    """Test sender rotation, daily limits, and reset logic."""

    def test_next_sender_picks_lowest_count(self):
        """The sender with the fewest sends today should be returned."""
        senders = _make_senders(3)
        pool = SenderPool(senders, daily_limit=10)

        # Record some sends to make counts unequal
        pool.record_send("sender1@test.com")
        pool.record_send("sender1@test.com")
        pool.record_send("sender2@test.com")

        # sender3 has 0 sends, should be picked
        result = pool.next_sender()
        assert result is not None
        assert result.email == "sender3@test.com"

    def test_daily_limit_enforcement(self):
        """All senders at daily limit should return None."""
        senders = _make_senders(2)
        pool = SenderPool(senders, daily_limit=2)

        for _ in range(2):
            pool.record_send("sender1@test.com")
            pool.record_send("sender2@test.com")

        result = pool.next_sender()
        assert result is None

    def test_partial_exhaustion(self):
        """If one sender is exhausted, the other should still be returned."""
        senders = _make_senders(2)
        pool = SenderPool(senders, daily_limit=2)

        pool.record_send("sender1@test.com")
        pool.record_send("sender1@test.com")

        result = pool.next_sender()
        assert result is not None
        assert result.email == "sender2@test.com"

    def test_reset_daily(self):
        """Counts should be zero after reset_daily."""
        senders = _make_senders(2)
        pool = SenderPool(senders, daily_limit=2)

        pool.record_send("sender1@test.com")
        pool.record_send("sender1@test.com")

        pool.reset_daily()

        assert pool.get_count("sender1@test.com") == 0
        assert pool.get_count("sender2@test.com") == 0

    def test_empty_pool_returns_none(self):
        """A pool with no senders always returns None."""
        pool = SenderPool([], daily_limit=10)
        assert pool.next_sender() is None

    def test_auto_reset_on_date_change(self):
        """Counts should auto-reset when date changes."""
        senders = _make_senders(1)
        pool = SenderPool(senders, daily_limit=2)
        pool.record_send("sender1@test.com")
        pool.record_send("sender1@test.com")

        assert pool.next_sender() is None

        # Simulate date change by backdating the last_reset_date
        for state in pool._states:
            state.last_reset_date = date(2020, 1, 1)

        result = pool.next_sender()
        assert result is not None
        assert result.email == "sender1@test.com"

    def test_get_count(self):
        """get_count returns accurate daily count per sender."""
        senders = _make_senders(2)
        pool = SenderPool(senders, daily_limit=10)

        pool.record_send("sender1@test.com")
        pool.record_send("sender1@test.com")
        pool.record_send("sender2@test.com")

        assert pool.get_count("sender1@test.com") == 2
        assert pool.get_count("sender2@test.com") == 1
        assert pool.get_count("nonexistent@test.com") == 0


# -- Delay tests --


class TestDelays:
    """Test randomized delay computation."""

    def test_delay_within_range(self):
        """Delay should be within min/max +/- 20% jitter."""
        min_d, max_d = 100, 200
        for _ in range(100):
            delay = _compute_delay(min_d, max_d)
            # Absolute bounds: min_d * 0.8 to max_d * 1.2
            assert delay >= min_d * 0.8 - 1  # small tolerance
            assert delay <= max_d * 1.2 + 1

    def test_delay_non_negative(self):
        """Delay should never be negative."""
        for _ in range(100):
            delay = _compute_delay(0, 1)
            assert delay >= 0.0

    def test_delay_varies(self):
        """Multiple calls should produce varying results."""
        delays = {_compute_delay(100, 200) for _ in range(20)}
        # With 20 random draws, extremely unlikely to get all identical
        assert len(delays) > 1


# -- Business hours tests --


class TestBusinessHours:
    """Test business hours check."""

    def test_within_business_hours(self):
        """Should return True during business hours on a weekday."""
        fake_now = datetime(2026, 4, 8, 10, 30)  # Wednesday 10:30
        with patch("src.email.pool.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_business_hours() is True

    def test_before_business_hours(self):
        """Should return False before 8 AM."""
        fake_now = datetime(2026, 4, 8, 7, 59)  # Wednesday 7:59
        with patch("src.email.pool.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_business_hours() is False

    def test_after_business_hours(self):
        """Should return False at or after 6 PM."""
        fake_now = datetime(2026, 4, 8, 18, 0)  # Wednesday 18:00
        with patch("src.email.pool.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_business_hours() is False

    def test_weekend(self):
        """Should return False on weekends regardless of hour."""
        fake_now = datetime(2026, 4, 11, 12, 0)  # Saturday noon
        with patch("src.email.pool.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_business_hours() is False


# -- Block-to-text tests --


class TestBlocksToText:
    """Test Notion block content extraction."""

    def test_paragraph_extraction(self):
        """Should extract paragraph text."""
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "Line one"}]
                },
            },
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "Line two"}]
                },
            },
        ]
        result = _blocks_to_plain_text(blocks)
        assert result == "Line one\nLine two"

    def test_empty_blocks(self):
        """Should return empty string for no blocks."""
        assert _blocks_to_plain_text([]) == ""

    def test_mixed_block_types(self):
        """Should handle heading and other block types."""
        blocks = [
            {
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"plain_text": "Title"}]
                },
            },
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "Body text"}]
                },
            },
        ]
        result = _blocks_to_plain_text(blocks)
        assert "Title" in result
        assert "Body text" in result


# -- send_batch tests --


@pytest.mark.asyncio
async def test_send_batch_success():
    """Successful send should update Notion status to Sent."""
    pages = [_make_email_page("e1", "Test Subject")]
    config = _make_config()
    pool = SenderPool(config.senders, config.email_daily_limit)
    notion = _make_notion_clients(approved=pages)

    with patch("src.email.sender._send_smtp") as mock_smtp:
        await send_batch(pages, pool, config, notion)
        mock_smtp.assert_called_once()

    # Verify Notion was updated with Sent status
    notion.emails._client.update_page.assert_awaited()
    update_call = notion.emails._client.update_page.call_args
    props = update_call[0][1]
    assert props["Status"] == {"select": {"name": "Sent"}}
    assert "Sender Address" in props
    assert "Sent At" in props


@pytest.mark.asyncio
async def test_send_batch_smtp_failure_marks_failed():
    """SMTP failure should mark email as Failed in Notion."""
    pages = [_make_email_page("e1", "Test Subject")]
    config = _make_config()
    pool = SenderPool(config.senders, config.email_daily_limit)
    notion = _make_notion_clients(approved=pages)

    with patch(
        "src.email.sender._send_smtp",
        side_effect=smtplib.SMTPException("Connection refused"),
    ):
        await send_batch(pages, pool, config, notion)

    update_call = notion.emails._client.update_page.call_args
    props = update_call[0][1]
    assert props["Status"] == {"select": {"name": "Failed"}}


@pytest.mark.asyncio
async def test_send_batch_fail_threshold_stops():
    """Reaching 15% fail rate should stop further sending."""
    # Create 10 pages. First send fails (1 fail / 1 total = 100% > 15%),
    # so the loop should stop before attempting the second email.
    pages = [_make_email_page(f"e{i}", f"Subject {i}") for i in range(10)]
    config = _make_config()
    pool = SenderPool(config.senders, config.email_daily_limit)
    notion = _make_notion_clients(approved=pages)

    call_count = {"n": 0}

    def always_fail(*args, **kwargs):
        call_count["n"] += 1
        raise smtplib.SMTPException("fail")

    with patch("src.email.sender._send_smtp", side_effect=always_fail):
        await send_batch(pages, pool, config, notion)

    # First send fails -> 100% fail rate -> stops before second attempt
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_send_batch_exhausted_senders_stops():
    """Should stop when all senders hit daily limit."""
    pages = [_make_email_page(f"e{i}", f"Subject {i}") for i in range(5)]
    config = _make_config(email_daily_limit=1)
    pool = SenderPool(config.senders, config.email_daily_limit)
    notion = _make_notion_clients(approved=pages)

    call_count = {"n": 0}

    def counting_smtp(*args, **kwargs):
        call_count["n"] += 1

    with patch("src.email.sender._send_smtp", side_effect=counting_smtp):
        await send_batch(pages, pool, config, notion)

    # 2 senders with limit 1 each -> max 2 sends
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_send_batch_no_recipient_skips():
    """Email with no recipient should be skipped, not crash."""
    pages = [_make_email_page("e1", "Test Subject")]
    config = _make_config()
    pool = SenderPool(config.senders, config.email_daily_limit)
    notion = _make_notion_clients(approved=pages, recipient_email="")

    with patch("src.email.sender._send_smtp") as mock_smtp:
        await send_batch(pages, pool, config, notion)
        mock_smtp.assert_not_called()


# -- Worker loop tests --


@pytest.mark.asyncio
async def test_worker_disabled_when_no_smtp():
    """Worker should sleep (not crash) when SMTP host is empty."""
    config = _make_config(smtp_host="")
    notion = _make_notion_clients()

    call_count = {"n": 0}

    original_sleep = asyncio.sleep

    async def counting_sleep(duration):
        call_count["n"] += 1
        if call_count["n"] >= 1:
            raise _StopLoop()

    with patch("src.email.sender.asyncio.sleep", side_effect=counting_sleep):
        with pytest.raises(_StopLoop):
            await email_sender_worker(config, notion)

    # Should have slept for 3600 (the SMTP-disabled sleep)
    assert call_count["n"] >= 1


@pytest.mark.asyncio
async def test_worker_sleeps_outside_business_hours():
    """Worker should sleep outside business hours."""
    config = _make_config()
    notion = _make_notion_clients()

    call_count = {"n": 0}

    async def counting_sleep(duration):
        call_count["n"] += 1
        if call_count["n"] >= 1:
            raise _StopLoop()

    with patch("src.email.sender.is_business_hours", return_value=False):
        with patch(
            "src.email.sender.asyncio.sleep", side_effect=counting_sleep
        ):
            with pytest.raises(_StopLoop):
                await email_sender_worker(config, notion)

    assert call_count["n"] >= 1


class _StopLoop(Exception):
    """Sentinel exception to break out of the infinite worker loop."""

    pass
