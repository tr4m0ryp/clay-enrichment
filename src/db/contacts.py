"""
Async Postgres operations for the contacts table.

Replaces src/notion/databases_contacts.py with asyncpg queries
against the contacts table defined in schema/001_init.sql.

Also manages contact_campaign_links (many-to-many join) so that
every contact is linked to the campaign that discovered it.
"""

import logging
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

CONTACT_STATUSES = ("Found", "Enriched", "Researched", "Email Generated")


class ContactsDB:
    """
    Typed CRUD operations for the contacts table.

    Accepts a shared asyncpg pool and exposes the same method interface
    as the Notion-backed ContactsDB it replaces.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # -- Lookups ---------------------------------------------------------------

    async def find_by_email(self, email_addr: str) -> dict | None:
        """
        Find a contact by exact email address match.

        Returns the matching row as a dict, or None if not found.
        """
        if not email_addr:
            return None

        row = await self._pool.fetchrow(
            "SELECT * FROM contacts WHERE email = $1 LIMIT 1",
            email_addr,
        )
        if row is None:
            return None
        return dict(row)

    async def get_contacts_for_company(self, company_id: str) -> list[dict]:
        """Fetch all contacts linked to a specific company."""
        rows = await self._pool.fetch(
            "SELECT * FROM contacts WHERE company_id = $1 "
            "ORDER BY created_at DESC",
            UUID(company_id),
        )
        return [dict(r) for r in rows]

    # -- Create ----------------------------------------------------------------

    async def create_contact(
        self,
        name: str,
        company_id: str,
        campaign_id: str,
        job_title: str = "",
        email_addr: str = "",
        email_verified: bool = False,
        linkedin_url: str = "",
        status: str = "Enriched",
        context: str = "",
        body: str = "",
    ) -> dict | None:
        """
        Create a contact with email-based dedup.

        If a contact with the same email already exists, creation is
        skipped and None is returned. On success the contact is also
        linked to the campaign via contact_campaign_links.
        """
        if email_addr:
            existing = await self.find_by_email(email_addr)
            if existing:
                logger.info(
                    "Skipping contact '%s': email '%s' already exists",
                    name,
                    email_addr,
                )
                return None

        if status not in CONTACT_STATUSES:
            logger.warning(
                "Invalid contact status '%s', defaulting to Enriched", status
            )
            status = "Enriched"

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "INSERT INTO contacts "
                    "(name, job_title, email, email_verified, linkedin_url, "
                    " company_id, status, context, body) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
                    "RETURNING *",
                    name,
                    job_title or None,
                    email_addr or None,
                    email_verified,
                    linkedin_url or None,
                    UUID(company_id) if company_id else None,
                    status,
                    context or None,
                    body,
                )

                # Link contact to campaign
                await conn.execute(
                    "INSERT INTO contact_campaign_links (contact_id, campaign_id) "
                    "VALUES ($1, $2) "
                    "ON CONFLICT DO NOTHING",
                    row["id"],
                    UUID(campaign_id),
                )

        logger.info("Created contact: %s (%s)", name, row["id"])
        return dict(row)

    # -- Update ----------------------------------------------------------------

    async def update_contact(self, contact_id: str, **fields) -> dict:
        """
        Update arbitrary columns on an existing contact.

        Accepts keyword arguments matching column names. Unknown keys
        are silently ignored.

        Returns the updated row.
        """
        allowed = {
            "name", "job_title", "email", "email_verified",
            "linkedin_url", "company_id", "status", "context", "body",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            row = await self._pool.fetchrow(
                "SELECT * FROM contacts WHERE id = $1", UUID(contact_id)
            )
            return dict(row)

        # Cast company_id to UUID if present
        if "company_id" in updates and updates["company_id"] is not None:
            updates["company_id"] = UUID(updates["company_id"])

        set_clauses = []
        values = []
        for i, (col, val) in enumerate(updates.items(), start=1):
            set_clauses.append(f"{col} = ${i}")
            values.append(val)

        values.append(UUID(contact_id))
        query = (
            f"UPDATE contacts SET {', '.join(set_clauses)} "
            f"WHERE id = ${len(values)} "
            "RETURNING *"
        )
        row = await self._pool.fetchrow(query, *values)
        return dict(row)

    # -- Body helpers ----------------------------------------------------------

    async def get_body(self, contact_id: str) -> str:
        """Return the body text for a contact."""
        row = await self._pool.fetchrow(
            "SELECT body FROM contacts WHERE id = $1",
            UUID(contact_id),
        )
        if row is None:
            return ""
        return row["body"] or ""

    async def set_body(self, contact_id: str, body: str) -> None:
        """Replace the body text for a contact."""
        await self._pool.execute(
            "UPDATE contacts SET body = $1 WHERE id = $2",
            body,
            UUID(contact_id),
        )
