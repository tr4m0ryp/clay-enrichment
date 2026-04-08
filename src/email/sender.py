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
    smtp_host: str,
    smtp_port: int,
    sender: SenderAccount,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    """
    Send a single email via SMTP with STARTTLS.

    Opens a fresh connection for each email (connect, auth, send, close).

    Args:
        smtp_host: SMTP server hostname.
        smtp_port: SMTP server port (typically 587).
        sender: The SenderAccount to authenticate with.
        recipient: The recipient email address.
        subject: The email subject line.
        body: The email body as plain text.

    Raises:
        smtplib.SMTPException: On any SMTP error.
        OSError: On connection failure.
        TimeoutError: If the connection or send exceeds the timeout.
    """
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
    """
    Extract the recipient email from the Contact linked to an email page.

    Args:
        email_page: The Notion email page object.
        notion_clients: Object with .contacts attribute (ContactsDB).

    Returns:
        The recipient email address, or empty string if not found.
    """
    contact_ids = extract_relation_ids(email_page, "Contact")
    if not contact_ids:
        return ""

    contact_id = contact_ids[0]
    client = notion_clients.contacts._client
    page = await client._call(
        client._sdk.pages.retrieve, page_id=contact_id
    )
    return extract_email(page, "Email")


async def _send_one(
    email_page: dict,
    sender_pool: SenderPool,
    config: Config,
    notion_clients: Any,
) -> bool | None:
    """
    Attempt to send a single email and update Notion accordingly.

    Args:
        email_page: The Notion email page object.
        sender_pool: The SenderPool for sender selection.
        config: Application configuration.
        notion_clients: Object with .emails and .contacts attributes.

    Returns:
        True on success, False on failure, None if skipped (no sender
        or no recipient).
    """
    page_id = email_page["id"]
    subject = extract_title(email_page, "Subject")

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
    approved: list[dict],
    sender_pool: SenderPool,
    config: Config,
    notion_clients: Any,
) -> None:
    """
    Send a batch of approved emails with rotation, delays, and safety rails.

    Stops sending if the fail rate reaches 15% or all senders are exhausted.

    Args:
        approved: List of approved email page objects from Notion.
        sender_pool: The SenderPool managing sender rotation.
        config: Application configuration.
        notion_clients: Object with .emails and .contacts attributes.
    """
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
    """
    Main worker loop: polls for approved emails and sends with rotation.

    Runs continuously. Sleeps when SMTP is not configured, outside
    business hours, or when no approved emails are pending.

    Args:
        config: Application configuration with SMTP settings.
        notion_clients: Object with .emails and .contacts database accessors.
    """
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
