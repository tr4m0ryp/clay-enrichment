"""
Async Postgres operations for the emails table.

Queries the emails table defined in schema/001_init.sql via asyncpg.
"""

import logging
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

EMAIL_STATUSES = ("Pending Review", "Approved", "Sent", "Rejected", "Failed")


class EmailsDB:
    """
    Typed CRUD operations for the emails table.

    Accepts a shared asyncpg pool.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # -- Queries ---------------------------------------------------------------

    async def get_pending_review(self) -> list[dict]:
        """Fetch all emails with status = 'Pending Review'."""
        rows = await self._pool.fetch(
            "SELECT * FROM emails WHERE status = $1 ORDER BY created_at DESC",
            "Pending Review",
        )
        return [dict(r) for r in rows]

    async def get_approved_emails(self) -> list[dict]:
        """Fetch all emails with status = 'Approved' (ready to send)."""
        rows = await self._pool.fetch(
            "SELECT * FROM emails WHERE status = $1 ORDER BY created_at DESC",
            "Approved",
        )
        return [dict(r) for r in rows]

    async def get_emails_for_campaign(self, campaign_id: str) -> list[dict]:
        """Fetch all emails linked to a specific campaign."""
        rows = await self._pool.fetch(
            "SELECT * FROM emails WHERE campaign_id = $1 "
            "ORDER BY created_at DESC",
            UUID(campaign_id),
        )
        return [dict(r) for r in rows]

    # -- Create ----------------------------------------------------------------

    async def create_email(
        self,
        subject: str,
        contact_id: str,
        campaign_id: str,
        sender_address: str = "",
        body: str = "",
    ) -> dict:
        """
        Insert a new email draft with status 'Pending Review'.

        The full email body is stored as TEXT in the body column.

        Returns the created row.
        """
        row = await self._pool.fetchrow(
            "INSERT INTO emails "
            "(subject, contact_id, campaign_id, status, sender_address, "
            " body, bounce) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7) "
            "RETURNING *",
            subject,
            UUID(contact_id),
            UUID(campaign_id),
            "Pending Review",
            sender_address or None,
            body,
            False,
        )
        logger.info("Created email draft: %s (%s)", subject, row["id"])
        return dict(row)

    # -- Status updates --------------------------------------------------------

    async def update_status(self, email_id: str, status: str) -> dict:
        """
        Update the status of an email.

        When status is set to 'Sent', sent_at is automatically
        populated with the current timestamp.

        Raises ValueError for invalid status values.
        """
        if status not in EMAIL_STATUSES:
            raise ValueError(
                f"Invalid email status '{status}'. "
                f"Must be one of: {EMAIL_STATUSES}"
            )

        if status == "Sent":
            row = await self._pool.fetchrow(
                "UPDATE emails SET status = $1, sent_at = now() "
                "WHERE id = $2 RETURNING *",
                status,
                UUID(email_id),
            )
        else:
            row = await self._pool.fetchrow(
                "UPDATE emails SET status = $1 "
                "WHERE id = $2 RETURNING *",
                status,
                UUID(email_id),
            )

        return dict(row)

    async def mark_bounced(self, email_id: str) -> dict:
        """
        Mark an email as bounced and set status to Failed.

        Returns the updated row.
        """
        row = await self._pool.fetchrow(
            "UPDATE emails SET bounce = true, status = $1 "
            "WHERE id = $2 RETURNING *",
            "Failed",
            UUID(email_id),
        )
        return dict(row)
