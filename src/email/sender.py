import os
import time
from collections import defaultdict

from src.email.smtp_client import send_email
from src.tools.notion import get_emails_by_status, update_email_status
from src.utils import log_status, log_success, log_error


def run_email_sender():
    """
    Runs the email sender loop. Polls the Notion Emails database for
    emails with "Approved" status, sends them using round-robin domain
    rotation across configured sender addresses, and updates their status
    to "Sent" in Notion.

    Respects configurable delays between sends and per-sender hourly limits.
    Runs indefinitely until interrupted with Ctrl+C.

    Configuration from environment variables:
        EMAIL_SENDER_ADDRESSES: Comma-separated list of sender email addresses.
        EMAIL_SMTP_HOST: SMTP server hostname.
        EMAIL_SMTP_PORT: SMTP server port (default 587).
        EMAIL_SMTP_PASSWORD: SMTP authentication password.
        EMAIL_DELAY_SECONDS: Seconds to wait between sending emails (default 15).
        EMAIL_MAX_PER_SENDER_PER_HOUR: Max emails per sender per hour (default 20).
        EMAIL_POLL_INTERVAL_SECONDS: Seconds between Notion polling cycles (default 300).
    """
    sender_addresses = _get_sender_addresses()
    if not sender_addresses:
        log_error("No sender addresses configured. Set EMAIL_SENDER_ADDRESSES in .env")
        return

    smtp_config = {
        "host": os.getenv("EMAIL_SMTP_HOST", ""),
        "port": os.getenv("EMAIL_SMTP_PORT", "587"),
        "password": os.getenv("EMAIL_SMTP_PASSWORD", ""),
    }

    if not smtp_config["host"]:
        log_error("EMAIL_SMTP_HOST is not set in .env")
        return

    delay = int(os.getenv("EMAIL_DELAY_SECONDS", "15"))
    max_per_hour = int(os.getenv("EMAIL_MAX_PER_SENDER_PER_HOUR", "20"))
    poll_interval = int(os.getenv("EMAIL_POLL_INTERVAL_SECONDS", "300"))

    rotator = SenderRotator(sender_addresses, max_per_hour)

    log_status("Email sender started. Polling Notion for approved emails...")

    try:
        while True:
            approved_emails = get_emails_by_status("Approved")

            if not approved_emails:
                log_status(f"No approved emails found. Checking again in {poll_interval}s...")
                time.sleep(poll_interval)
                continue

            log_status(f"Found {len(approved_emails)} approved emails to send")

            for email_record in approved_emails:
                # Get next available sender
                sender = rotator.get_next_sender()
                if not sender:
                    log_status("All senders at hourly limit. Waiting 60 seconds...")
                    time.sleep(60)
                    rotator.cleanup_old_timestamps()
                    sender = rotator.get_next_sender()
                    if not sender:
                        log_error("Still no senders available. Skipping this cycle.")
                        break

                # Send the email
                log_status(f"Sending to {email_record.recipient_email} via {sender}")
                success = send_email(
                    sender=sender,
                    recipient=email_record.recipient_email,
                    subject=email_record.subject,
                    body=email_record.body,
                    smtp_config=smtp_config,
                )

                if success:
                    rotator.record_send(sender)
                    update_email_status(
                        email_record.notion_page_id,
                        status="Sent",
                        sender=sender,
                    )
                    log_success(f"Sent to {email_record.recipient_email} via {sender}")
                else:
                    log_error(f"Failed to send to {email_record.recipient_email}")

                # Delay between sends
                time.sleep(delay)

            log_status(f"Batch complete. Checking again in {poll_interval}s...")
            time.sleep(poll_interval)

    except KeyboardInterrupt:
        log_status("\nEmail sender stopped.")


class SenderRotator:
    """
    Manages round-robin rotation across multiple sender email addresses
    with per-sender hourly rate limits.

    Parameters:
        addresses: List of sender email addresses.
        max_per_hour: Maximum number of emails each sender can send per hour.
    """

    def __init__(self, addresses, max_per_hour):
        """
        Initializes the rotator with the given addresses and hourly limit.

        Parameters:
            addresses: List of sender email address strings.
            max_per_hour: Maximum sends per sender per rolling hour.
        """
        self.addresses = addresses
        self.max_per_hour = max_per_hour
        self.current_index = 0
        self.send_timestamps = defaultdict(list)

    def get_next_sender(self):
        """
        Returns the next available sender address that has not exceeded
        its hourly limit. Cycles through all addresses in round-robin
        order.

        Returns:
            A sender email address string, or None if all senders are
            at their hourly limit.
        """
        self.cleanup_old_timestamps()

        for _ in range(len(self.addresses)):
            sender = self.addresses[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.addresses)

            if len(self.send_timestamps[sender]) < self.max_per_hour:
                return sender

        return None

    def record_send(self, sender):
        """
        Records a send event for the given sender address.

        Parameters:
            sender: The sender email address that was used.
        """
        self.send_timestamps[sender].append(time.time())

    def cleanup_old_timestamps(self):
        """
        Removes send timestamps older than one hour from all senders.
        Called automatically before checking availability.
        """
        cutoff = time.time() - 3600
        for sender in self.addresses:
            self.send_timestamps[sender] = [
                ts for ts in self.send_timestamps[sender]
                if ts > cutoff
            ]


def _get_sender_addresses():
    """
    Reads the comma-separated list of sender email addresses from
    the EMAIL_SENDER_ADDRESSES environment variable.

    Returns:
        A list of sender address strings, or empty list if not configured.
    """
    raw = os.getenv("EMAIL_SENDER_ADDRESSES", "")
    if not raw:
        return []
    return [addr.strip() for addr in raw.split(",") if addr.strip()]
