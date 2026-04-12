"""
Async CRUD operations for the contact_campaigns junction table.

Replaces src/notion/databases_contact_campaigns.py with asyncpg queries
against the Postgres contact_campaigns table (see schema/001_init.sql).

Each record pairs one contact with one campaign, storing campaign-specific
relevance score, personalized context, and outreach status. Dedup is
enforced by a UNIQUE(contact_id, campaign_id) constraint.
"""

from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)

OUTREACH_STATUSES: list[str] = [
    "New",
    "Email Pending Review",
    "Email Approved",
    "Sent",
    "Replied",
    "Meeting Booked",
]

INDUSTRY_OPTIONS: list[str] = ["Fashion", "Streetwear", "Lifestyle", "Other"]

__all__ = ["ContactCampaignsDB", "OUTREACH_STATUSES", "INDUSTRY_OPTIONS"]


def _row_to_dict(row: asyncpg.Record | None) -> dict | None:
    """Convert an asyncpg Record to a plain dict, or None."""
    return dict(row) if row is not None else None


def _rows_to_dicts(rows: list[asyncpg.Record]) -> list[dict]:
    """Convert a list of asyncpg Records to a list of plain dicts."""
    return [dict(r) for r in rows]


class ContactCampaignsDB:
    """
    Typed operations for the contact_campaigns junction table.

    Accepts an asyncpg connection pool in __init__. All methods are async
    and return plain dicts (matching the Notion-era interface).
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    async def find_by_contact_campaign(
        self, contact_id: str, campaign_id: str
    ) -> dict | None:
        """
        Find an existing junction record for a contact + campaign pair.

        Returns the matching row as a dict, or None if not found.
        """
        row = await self._pool.fetchrow(
            "SELECT * FROM contact_campaigns "
            "WHERE contact_id = $1 AND campaign_id = $2",
            contact_id,
            campaign_id,
        )
        return _row_to_dict(row)

    async def get_entries_for_campaign(self, campaign_id: str) -> list[dict]:
        """Return all junction entries for a campaign regardless of score."""
        rows = await self._pool.fetch(
            "SELECT * FROM contact_campaigns WHERE campaign_id = $1",
            campaign_id,
        )
        return _rows_to_dicts(rows)

    async def get_high_priority(
        self, campaign_id: str, min_score: float = 7.0
    ) -> list[dict]:
        """
        Return entries with both relevance_score AND company_fit_score >= min_score.

        This is the critical leads query used to select contacts for outreach.
        """
        rows = await self._pool.fetch(
            "SELECT * FROM contact_campaigns "
            "WHERE campaign_id = $1 "
            "AND relevance_score >= $2 "
            "AND company_fit_score >= $2",
            campaign_id,
            min_score,
        )
        return _rows_to_dicts(rows)

    async def get_unscored_entries(self, campaign_id: str) -> list[dict]:
        """Return entries for a campaign where relevance_score is NULL or 0."""
        rows = await self._pool.fetch(
            "SELECT * FROM contact_campaigns "
            "WHERE campaign_id = $1 "
            "AND (relevance_score IS NULL OR relevance_score = 0)",
            campaign_id,
        )
        return _rows_to_dicts(rows)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_entry(
        self,
        contact_id: str,
        campaign_id: str,
        company_id: str,
        contact_name: str,
        campaign_name: str,
        job_title: str = "",
        company_name: str = "",
        email_addr: str = "",
        email_verified: bool = False,
        linkedin_url: str = "",
        industry: str = "Other",
        location: str = "",
        company_fit_score: float = 0,
        relevance_score: float = 0,
        score_reasoning: str = "",
        personalized_context: str = "",
        context: str = "",
    ) -> dict | None:
        """
        Create a junction record with dedup by contact_id + campaign_id.

        Uses INSERT ... ON CONFLICT DO NOTHING. Returns the new row as a
        dict, or None if the pair already exists.
        """
        if industry not in INDUSTRY_OPTIONS:
            industry = "Other"

        entry_name = f"{contact_name} - {campaign_name}"

        row = await self._pool.fetchrow(
            """
            INSERT INTO contact_campaigns (
                contact_id, campaign_id, company_id, name,
                job_title, company_name, email, email_verified,
                linkedin_url, industry, location,
                company_fit_score, relevance_score,
                score_reasoning, personalized_context, context,
                email_subject, outreach_status
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8,
                $9, $10, $11,
                $12, $13,
                $14, $15, $16,
                NULL, 'New'
            )
            ON CONFLICT (contact_id, campaign_id) DO NOTHING
            RETURNING *
            """,
            contact_id,
            campaign_id,
            company_id,
            entry_name,
            job_title,
            company_name,
            email_addr or None,
            email_verified,
            linkedin_url or None,
            industry,
            location,
            company_fit_score,
            relevance_score,
            score_reasoning,
            personalized_context,
            context,
        )

        if row is None:
            logger.info(
                "Skipping junction entry: contact '%s' + campaign '%s' already exists",
                contact_id,
                campaign_id,
            )
            return None

        logger.info("Created junction entry: %s (%s)", entry_name, row["id"])
        return dict(row)

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    async def update_entry(self, entry_id: str, properties: dict) -> None:
        """
        Apply a partial column update to a junction record.

        Args:
            entry_id: The UUID primary key of the junction record.
            properties: Column name -> value pairs to update.
        """
        if not properties:
            return

        set_parts: list[str] = []
        values: list = []
        for i, (col, val) in enumerate(properties.items(), start=1):
            set_parts.append(f"{col} = ${i}")
            values.append(val)

        # entry_id is the last parameter
        values.append(entry_id)
        id_param = f"${len(values)}"

        sql = (
            f"UPDATE contact_campaigns SET {', '.join(set_parts)} "
            f"WHERE id = {id_param}"
        )
        await self._pool.execute(sql, *values)

    async def update_score(
        self,
        entry_id: str,
        relevance_score: float,
        score_reasoning: str,
        personalized_context: str,
    ) -> None:
        """Update relevance_score, score_reasoning, and personalized_context."""
        await self._pool.execute(
            "UPDATE contact_campaigns "
            "SET relevance_score = $1, score_reasoning = $2, "
            "    personalized_context = $3 "
            "WHERE id = $4",
            relevance_score,
            score_reasoning,
            personalized_context,
            entry_id,
        )

    async def update_email_subject(self, entry_id: str, subject: str) -> None:
        """Update the email_subject field after email generation."""
        await self._pool.execute(
            "UPDATE contact_campaigns SET email_subject = $1 WHERE id = $2",
            subject,
            entry_id,
        )

    async def update_outreach_status(self, entry_id: str, status: str) -> None:
        """
        Update the outreach_status. Raises ValueError for invalid values.

        Valid values: New, Email Pending Review, Email Approved, Sent,
        Replied, Meeting Booked.
        """
        if status not in OUTREACH_STATUSES:
            raise ValueError(
                f"Invalid outreach status '{status}'. "
                f"Must be one of: {', '.join(OUTREACH_STATUSES)}"
            )
        await self._pool.execute(
            "UPDATE contact_campaigns SET outreach_status = $1 WHERE id = $2",
            status,
            entry_id,
        )
