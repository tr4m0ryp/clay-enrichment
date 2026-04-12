"""
Async CRUD operations for the companies table using asyncpg.

Replaces src/notion/databases_companies.py with direct Postgres access.
Handles dedup logic, campaign linking via company_campaigns join table,
and body text storage.
"""

import logging
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

COMPANY_STATUSES = (
    "Discovered",
    "Enriched",
    "Partially Enriched",
    "Contacts Found",
)

INDUSTRY_OPTIONS = ("Fashion", "Streetwear", "Lifestyle", "Other")

# Columns allowed in update_company to prevent SQL injection via key names.
_ALLOWED_COLUMNS = frozenset({
    "name", "website", "industry", "location", "size",
    "dpp_fit_score", "status", "source_query", "body",
    "last_enriched_at",
})


class CompaniesDB:
    """Typed asyncpg operations for the companies table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    async def find_by_name(self, name: str) -> dict | None:
        """Find a company by exact name match."""
        row = await self._pool.fetchrow(
            "SELECT * FROM companies WHERE name = $1 LIMIT 1",
            name,
        )
        return dict(row) if row else None

    async def find_by_domain(self, domain: str) -> dict | None:
        """Find a company whose website contains the given domain."""
        row = await self._pool.fetchrow(
            "SELECT * FROM companies WHERE website ILIKE '%' || $1 || '%' LIMIT 1",
            domain,
        )
        return dict(row) if row else None

    async def get_companies_by_status(self, status: str) -> list[dict]:
        """Fetch all companies with a given status."""
        rows = await self._pool.fetch(
            "SELECT * FROM companies WHERE status = $1 ORDER BY created_at",
            status,
        )
        return [dict(r) for r in rows]

    async def get_stale_companies(self, stale_days: int) -> list[dict]:
        """
        Fetch companies whose last_enriched_at is older than stale_days
        or NULL, excluding those still in Discovered status.
        """
        rows = await self._pool.fetch(
            """
            SELECT * FROM companies
            WHERE (
                last_enriched_at < now() - make_interval(days => $1)
                OR last_enriched_at IS NULL
            )
            AND status != 'Discovered'
            ORDER BY last_enriched_at NULLS FIRST
            """,
            stale_days,
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Create (with dedup + campaign linking)
    # ------------------------------------------------------------------

    async def create_company(
        self,
        name: str,
        campaign_id: str,
        *,
        website: str = "",
        industry: str = "Other",
        location: str = "",
        size: str = "",
        source_query: str = "",
        stale_days: int = 90,
    ) -> dict | None:
        """
        Create a company with dedup logic.

        If a company with the same name already exists and is recently
        enriched (within stale_days), creation is skipped but the campaign
        link is ensured. Returns None in that case.

        If it exists but is stale or not enriched, the campaign link is
        ensured and the existing row is returned for re-enrichment.

        Args:
            name: Company name.
            campaign_id: UUID string of the associated campaign.
            website: Company website URL.
            industry: Industry category (validated against INDUSTRY_OPTIONS).
            location: Location description.
            size: Company size description.
            source_query: The search query that found this company.
            stale_days: Threshold for considering enrichment stale.

        Returns:
            The created or existing company dict, or None if skipped.
        """
        cid = UUID(campaign_id)

        existing = await self.find_by_name(name)
        if existing:
            await self._link_campaign(existing["id"], cid)

            if self._is_recently_enriched(existing, stale_days):
                logger.info("Skipping company '%s': recently enriched", name)
                return None

            logger.info(
                "Company '%s' exists but stale, returning for re-enrichment",
                name,
            )
            return existing

        if industry not in INDUSTRY_OPTIONS:
            industry = "Other"

        row = await self._pool.fetchrow(
            """
            INSERT INTO companies (name, website, industry, location, size,
                                   status, source_query)
            VALUES ($1, $2, $3, $4, $5, 'Discovered', $6)
            RETURNING *
            """,
            name,
            website or None,
            industry,
            location or None,
            size or None,
            source_query or None,
        )
        company = dict(row)
        await self._link_campaign(company["id"], cid)
        logger.info("Created company: %s (%s)", name, company["id"])
        return company

    # ------------------------------------------------------------------
    # Update (dynamic SET builder)
    # ------------------------------------------------------------------

    async def update_company(
        self, company_id: str, properties: dict
    ) -> None:
        """
        Update columns on an existing company row.

        The properties dict maps column names (snake_case) to values.
        Only columns in _ALLOWED_COLUMNS are accepted.

        Args:
            company_id: UUID string of the company.
            properties: Column-name to value mapping.
        """
        if not properties:
            return

        sets: list[str] = []
        args: list = []
        for key, value in properties.items():
            if key not in _ALLOWED_COLUMNS:
                raise ValueError(f"Column '{key}' is not allowed in update")
            idx = len(args) + 1
            sets.append(f"{key} = ${idx}")
            args.append(value)

        args.append(UUID(company_id))
        query = (
            f"UPDATE companies SET {', '.join(sets)} "
            f"WHERE id = ${len(args)}"
        )
        await self._pool.execute(query, *args)

    # ------------------------------------------------------------------
    # Body operations
    # ------------------------------------------------------------------

    async def get_body(self, company_id: str) -> str:
        """Return the body text for a company, or empty string."""
        row = await self._pool.fetchrow(
            "SELECT body FROM companies WHERE id = $1",
            UUID(company_id),
        )
        if row is None:
            return ""
        return row["body"] or ""

    async def set_body(self, company_id: str, body: str) -> None:
        """Overwrite the body text for a company."""
        await self._pool.execute(
            "UPDATE companies SET body = $1 WHERE id = $2",
            body,
            UUID(company_id),
        )

    async def append_body(self, company_id: str, text: str) -> None:
        """Append text to the existing body, separated by double newline."""
        await self._pool.execute(
            """
            UPDATE companies
            SET body = CASE
                WHEN body = '' THEN $1
                ELSE body || E'\\n\\n' || $1
            END
            WHERE id = $2
            """,
            text,
            UUID(company_id),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _link_campaign(self, company_id: UUID, campaign_id: UUID) -> None:
        """Ensure a company_campaigns row exists. No-op on conflict."""
        await self._pool.execute(
            """
            INSERT INTO company_campaigns (company_id, campaign_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            company_id,
            campaign_id,
        )

    @staticmethod
    def _is_recently_enriched(company: dict, stale_days: int) -> bool:
        """Check if a company was enriched within the stale threshold."""
        if company.get("status") != "Enriched":
            return False

        last = company.get("last_enriched_at")
        if last is None:
            return False

        from datetime import datetime, timezone, timedelta

        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
        return last > cutoff
