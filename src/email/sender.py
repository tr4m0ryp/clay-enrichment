"""
SMTP email sending engine with safety rails.

Polls Notion for approved emails, sends via SMTP with round-robin
sender rotation, randomized delays, daily per-sender limits, business
hours enforcement, and automatic fail-rate hard stop.

Re-exports SenderPool and helpers from pool.py for external callers.
"""

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from src.config import Config, SenderAccount
from src.email.pool import (
    SenderPool,
    is_business_hours,
    compute_delay,
    blocks_to_plain_text,
)
from src.notion.prop_helpers import (
    extract_title,
    extract_relation_ids,
    extract_email,
    extract_select,
    rich_text_prop,
    select_prop,
    date_prop,
)

logger = logging.getLogger(__name__)

_SMTP_TIMEOUT_SECONDS = 30
_FAIL_RATE_THRESHOLD = 0.15

# Re-export for backward compatibility
__all__ = [
    "SenderPool",
    "is_business_hours",
    "compute_delay",
    "blocks_to_plain_text",
    "send_batch",
    "email_sender_worker",
]


def _send_smtp(
    smtp_host: str, smtp_port: int, sender: SenderAccount,
    recipient: str, subject: str, body: str,
) -> None:
    """Send a single email via SMTP/STARTTLS (fresh connection per email)."""
    msg = EmailMessage()
    msg["From"] = sender.email
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=_SMTP_TIMEOUT_SECONDS) as srv:
        srv.starttls()
        srv.login(sender.email, sender.password)
        srv.send_message(msg)


async def _get_recipient_email(
    email_page: dict, notion_clients: Any
) -> str:
    """Extract recipient email from the Contact linked to an email page."""
    contact_ids = extract_relation_ids(email_page, "Contact")
    if not contact_ids:
        return ""

    contact_id = contact_ids[0]
    client = notion_clients.contacts._client
    page = await client._call(
        client._sdk.pages.retrieve, page_id=contact_id
    )
    return extract_email(page, "Email")


async def _is_campaign_active(
    email_page: dict, notion_clients: Any
) -> bool:
    """Return True only if the email's campaign has Status=Active."""
    campaign_ids = extract_relation_ids(email_page, "Campaign")
    if not campaign_ids:
        logger.warning("Email %s has no campaign relation, blocking send",
                        email_page["id"])
        return False
    campaigns_db = getattr(notion_clients, "campaigns", None)
    if campaigns_db is None:
        return True  # cannot verify -- allow for backward compatibility
    try:
        client = campaigns_db._client
        page = await client._call(
            client._sdk.pages.retrieve, page_id=campaign_ids[0])
        return extract_select(page, "Status") == "Active"
    except Exception as exc:
        logger.warning("Campaign status check failed for email %s: %s",
                        email_page["id"], exc)
        return False  # fail closed


async def _update_junction_status(
    email_page: dict, status: str, notion_clients: Any
) -> None:
    """Update the junction table outreach status for an email's contact+campaign."""
    cc_db = getattr(notion_clients, "contact_campaigns", None)
    if cc_db is None:
        return
    contact_ids = extract_relation_ids(email_page, "Contact")
    campaign_ids = extract_relation_ids(email_page, "Campaign")
    if not contact_ids or not campaign_ids:
        return
    try:
        entry = await cc_db.find_by_contact_campaign(
            contact_ids[0], campaign_ids[0]
        )
        if entry:
            await cc_db.update_outreach_status(entry["id"], status)
    except Exception as exc:
        logger.warning("Junction status update to '%s' failed: %s", status, exc)


async def _send_one(
    email_page: dict, sender_pool: SenderPool,
    config: Config, notion_clients: Any,
) -> bool | None:
    """Send one email. Returns True/False/None (skipped)."""
    page_id = email_page["id"]
    subject = extract_title(email_page, "Subject")

    # Only send emails for Active campaigns
    if not await _is_campaign_active(email_page, notion_clients):
        logger.info(
            "Skipping email '%s' (page %s): campaign is not Active",
            subject, page_id,
        )
        return None

    sender = sender_pool.next_sender()
    if sender is None:
        logger.warning(
            "All senders exhausted daily limits. Cannot send '%s'.", subject
        )
        return None

    recipient = await _get_recipient_email(email_page, notion_clients)
    if not recipient:
        logger.warning(
            "No recipient email found for page %s, skipping.", page_id
        )
        return None

    body_blocks = await notion_clients.emails._client.get_page_body(page_id)
    body_text = blocks_to_plain_text(body_blocks)

    try:
        await asyncio.to_thread(
            _send_smtp,
            config.smtp_host,
            config.smtp_port,
            sender,
            recipient,
            subject,
            body_text,
        )
        sender_pool.record_send(sender.email)
        await notion_clients.emails._client.update_page(
            page_id,
            {
                "Status": select_prop("Sent"),
                "Sender Address": rich_text_prop(sender.email),
                "Sent At": date_prop(),
            },
        )
        await _update_junction_status(email_page, "Sent", notion_clients)
        logger.info("Sent '%s' to %s via %s", subject, recipient, sender.email)
        return True

    except Exception as exc:
        logger.error("Failed to send '%s' (page %s): %s", subject, page_id, exc)
        try:
            await notion_clients.emails._client.update_page(
                page_id, {"Status": select_prop("Failed")}
            )
        except Exception as update_exc:
            logger.error(
                "Failed to update status for page %s: %s", page_id, update_exc
            )
        return False


async def send_batch(
    approved: list[dict], sender_pool: SenderPool,
    config: Config, notion_clients: Any,
) -> None:
    """Send approved emails with rotation, delays, and fail-rate safety."""
    total = 0
    failures = 0

    for idx, email_page in enumerate(approved):
        if total > 0 and (failures / total) >= _FAIL_RATE_THRESHOLD:
            logger.error(
                "Fail rate %.0f%% reached threshold (%.0f%%). "
                "Stopping all sending. Sent %d, failed %d.",
                (failures / total) * 100,
                _FAIL_RATE_THRESHOLD * 100,
                total,
                failures,
            )
            return

        result = await _send_one(email_page, sender_pool, config, notion_clients)
        if result is None and sender_pool.next_sender() is None:
            logger.warning("All senders exhausted. Stopping batch after %d.", total)
            return
        elif result is True:
            total += 1
        elif result is False:
            total += 1
            failures += 1

        if idx < len(approved) - 1 and result is not None:
            delay = compute_delay(config.email_min_delay, config.email_max_delay)
            logger.debug("Waiting %.1f seconds before next send", delay)
            await asyncio.sleep(delay)


async def email_sender_worker(config: Config, notion_clients: Any) -> None:
    """Main worker loop: polls for approved emails and sends with rotation."""
    sender_pool = SenderPool(config.senders, config.email_daily_limit)

    while True:
        if not config.smtp_host:
            logger.info("Email sending disabled (no SMTP configured)")
            await asyncio.sleep(3600)
            continue

        if not is_business_hours():
            logger.debug("Outside business hours, sleeping")
            await asyncio.sleep(600)
            continue

        try:
            approved = await notion_clients.emails.get_approved_emails()
        except Exception as exc:
            logger.error("Failed to fetch approved emails: %s", exc)
            await asyncio.sleep(60)
            continue

        if approved:
            await send_batch(approved, sender_pool, config, notion_clients)

        await asyncio.sleep(60)
