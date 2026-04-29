"""
Async Postgres operations for the campaigns table.

Queries the campaigns table defined in schema/001_init.sql via asyncpg.
"""

import logging

import asyncpg

logger = logging.getLogger(__name__)

# Valid status values (matches CHECK constraint on campaigns.status)
CAMPAIGN_STATUSES = ("Active", "Paused", "Completed", "Abort")


class CampaignsDB:
    """
    Typed CRUD operations for the campaigns table.

    Accepts a shared asyncpg pool.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_active_campaigns(self) -> list[dict]:
        """Fetch all campaigns with status = 'Active'."""
        rows = await self._pool.fetch(
            "SELECT * FROM campaigns WHERE status = $1 ORDER BY created_at DESC",
            "Active",
        )
        return [dict(r) for r in rows]

    async def get_processable_campaigns(self) -> list[dict]:
        """
        Fetch campaigns eligible for enrichment processing.

        Returns campaigns with status in (Active, Paused, Completed) --
        everything except Abort.
        """
        rows = await self._pool.fetch(
            "SELECT * FROM campaigns "
            "WHERE status IN ($1, $2, $3) "
            "ORDER BY created_at DESC",
            "Active",
            "Paused",
            "Completed",
        )
        return [dict(r) for r in rows]

    async def get_all(self) -> list[dict]:
        """Fetch all campaigns regardless of status."""
        rows = await self._pool.fetch(
            "SELECT * FROM campaigns ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    async def find_by_name(self, name: str) -> dict | None:
        """
        Find a campaign by exact name match.

        Returns the matching row as a dict, or None if not found.
        """
        row = await self._pool.fetchrow(
            "SELECT * FROM campaigns WHERE name = $1 LIMIT 1",
            name,
        )
        if row is None:
            return None
        return dict(row)

    async def create_campaign(
        self,
        name: str,
        target_description: str = "",
        status: str = "Active",
    ) -> dict:
        """
        Insert a new campaign and return the created row.

        Falls back to 'Active' if an invalid status is provided.
        """
        if status not in CAMPAIGN_STATUSES:
            logger.warning(
                "Invalid campaign status '%s', defaulting to Active", status
            )
            status = "Active"

        row = await self._pool.fetchrow(
            "INSERT INTO campaigns (name, target_description, status) "
            "VALUES ($1, $2, $3) "
            "RETURNING *",
            name,
            target_description,
            status,
        )
        logger.info("Created campaign: %s (%s)", name, row["id"])
        return dict(row)

    async def update_status(self, campaign_id: str, status: str) -> None:
        """
        Update the status of an existing campaign.

        Raises ValueError for invalid status values.
        """
        if status not in CAMPAIGN_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {CAMPAIGN_STATUSES}"
            )

        await self._pool.execute(
            "UPDATE campaigns SET status = $1, updated_at = now() WHERE id = $2",
            status,
            campaign_id,
        )

    async def increment_discovery_strategy_index(
        self, campaign_id: str,
    ) -> None:
        """Advance the 13-strategy rotation cursor by 1.

        Used by the discovery worker after each cycle so the next cycle
        picks the next strategy in the rotation. The increment is
        unbounded -- ``pick_strategy`` applies ``index % 13`` so an
        ever-growing counter is fine.
        """
        await self._pool.execute(
            """
            UPDATE campaigns
            SET discovery_strategy_index = discovery_strategy_index + 1,
                updated_at = now()
            WHERE id = $1
            """,
            campaign_id,
        )
