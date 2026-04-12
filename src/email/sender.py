"""
SMTP email sending engine with safety rails.

Polls Postgres for approved emails, sends via SMTP with round-robin
sender rotation, randomized delays, daily per-sender limits, business
hours enforcement, and automatic fail-rate hard stop.

Re-exports SenderPool and helpers from pool.py for external callers.
"""

import asyncio
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from src.config import Config, SenderAccount
from src.db.contacts import ContactsDB
from src.db.emails import EmailsDB
from src.email.pool import (
    SenderPool,
    is_business_hours,
    compute_delay,
)

logger = logging.getLogger(__name__)

_SMTP_TIMEOUT_SECONDS = 30
_FAIL_RATE_THRESHOLD = 0.15

# Re-export for backward compatibility
__all__ = [
    "SenderPool",
    "is_business_hours",
    "compute_delay",
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
    email_row: dict, db_clients: Any
) -> str:
    """Extract recipient email from the Contact linked to an email row."""
    contact_id = email_row.get("contact_id")
    if not contact_id:
        return ""

    contacts_db: ContactsDB = db_clients.contacts
    row = await contacts_db._pool.fetchrow(
        "SELECT email FROM contacts WHERE id = $1", contact_id
    )
    if row is None:
        return ""
    return row["email"] or ""


async def _is_campaign_active(
    email_row: dict, db_clients: Any
) -> bool:
    """Return True only if the email's campaign has status=Active."""
    campaign_id = email_row.get("campaign_id")
    if not campaign_id:
        logger.warning("Email %s has no campaign relation, blocking send",
                        email_row["id"])
        return False
    campaigns_db = getattr(db_clients, "campaigns", None)
    if campaigns_db is None:
        return True  # cannot verify -- allow for backward compatibility
    try:
        row = await campaigns_db._pool.fetchrow(
            "SELECT status FROM campaigns WHERE id = $1", campaign_id
        )
        if row is None:
            return False
        return row["status"] == "Active"
    except Exception as exc:
        logger.warning("Campaign status check failed for email %s: %s",
                        email_row["id"], exc)
        return False  # fail closed


async def _update_junction_status(
    email_row: dict, status: str, db_clients: Any
) -> None:
    """Update the junction table outreach status for an email's contact+campaign."""
    cc_db = getattr(db_clients, "contact_campaigns", None)
    if cc_db is None:
        return
    contact_id = email_row.get("contact_id")
    campaign_id = email_row.get("campaign_id")
    if not contact_id or not campaign_id:
        return
    try:
        entry = await cc_db.find_by_contact_campaign(
            str(contact_id), str(campaign_id)
        )
        if entry:
            await cc_db.update_outreach_status(entry["id"], status)
    except Exception as exc:
        logger.warning("Junction status update to '%s' failed: %s", status, exc)


async def _send_one(
    email_row: dict, sender_pool: SenderPool,
    config: Config, db_clients: Any,
) -> bool | None:
    """Send one email. Returns True/False/None (skipped)."""
    email_id = str(email_row["id"])
    subject = email_row["subject"]

    # Only send emails for Active campaigns
    if not await _is_campaign_active(email_row, db_clients):
        logger.info(
            "Skipping email '%s' (id %s): campaign is not Active",
            subject, email_id,
        )
        return None

    sender = sender_pool.next_sender()
    if sender is None:
        logger.warning(
            "All senders exhausted daily limits. Cannot send '%s'.", subject
        )
        return None

    recipient = await _get_recipient_email(email_row, db_clients)
    if not recipient:
        logger.warning(
            "No recipient email found for email %s, skipping.", email_id
        )
        return None

    body_text = email_row.get("body") or ""

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

        emails_db: EmailsDB = db_clients.emails
        await emails_db.update_status(email_id, "Sent")
        # Store the sender address used
        await emails_db._pool.execute(
            "UPDATE emails SET sender_address = $1 WHERE id = $2",
            sender.email,
            email_row["id"],
        )

        await _update_junction_status(email_row, "Sent", db_clients)
        logger.info("Sent '%s' to %s via %s", subject, recipient, sender.email)
        return True

    except Exception as exc:
        logger.error("Failed to send '%s' (id %s): %s", subject, email_id, exc)
        try:
            emails_db: EmailsDB = db_clients.emails
            await emails_db.update_status(email_id, "Failed")
        except Exception as update_exc:
            logger.error(
                "Failed to update status for email %s: %s", email_id, update_exc
            )
        return False


async def send_batch(
    approved: list[dict], sender_pool: SenderPool,
    config: Config, db_clients: Any,
) -> None:
    """Send approved emails with rotation, delays, and fail-rate safety."""
    total = 0
    failures = 0

    for idx, email_row in enumerate(approved):
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

        result = await _send_one(email_row, sender_pool, config, db_clients)
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


async def email_sender_worker(config: Config, db_clients: Any) -> None:
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
            emails_db: EmailsDB = db_clients.emails
            approved = await emails_db.get_approved_emails()
        except Exception as exc:
            logger.error("Failed to fetch approved emails: %s", exc)
            await asyncio.sleep(60)
            continue

        if approved:
            await send_batch(approved, sender_pool, config, db_clients)

        await asyncio.sleep(60)
