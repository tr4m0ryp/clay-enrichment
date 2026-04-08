"""
Typed CRUD operations for the Contacts Notion database.

Schema:
    Name (title), Job Title (rich_text), Email (email),
    Email Verified (checkbox), Phone (phone_number),
    LinkedIn URL (url), Company (relation->Companies),
    Status (select), Campaign (relation->Campaigns)
"""

import logging

from src.config import get_config
from src.notion.client import NotionClient
from src.notion.prop_helpers import (
    title_prop,
    rich_text_prop,
    select_prop,
    email_prop,
    phone_prop,
    url_prop,
    checkbox_prop,
    relation_prop,
    extract_email,
)

logger = logging.getLogger(__name__)

CONTACT_STATUSES = ("Found", "Enriched", "Email Generated")


class ContactsDB:
    """
    Typed operations for the Contacts database.

    Includes dedup logic: before creating, checks for existing contacts
    by email address. If a match exists, creation is skipped.
    """

    def __init__(self, client: NotionClient) -> None:
        """
        Initialise with a NotionClient instance.

        Args:
            client: The shared NotionClient to use for API calls.
        """
        self._client = client
        self._db_id = get_config().notion_contacts_db_id

    @property
    def db_id(self) -> str:
        """Return the contacts database ID from config."""
        return self._db_id

    @db_id.setter
    def db_id(self, value: str) -> None:
        """Allow overriding the database ID (used during setup)."""
        self._db_id = value

    async def find_by_email(self, email_addr: str) -> dict | None:
        """
        Find a contact by exact email address match.

        Args:
            email_addr: The email address to search for.

        Returns:
            The first matching page object, or None if not found.
        """
        if not email_addr:
            return None

        filter_obj = {
            "property": "Email",
            "email": {"equals": email_addr},
        }
        results = await self._client.query_database(
            self._db_id, filter_obj=filter_obj
        )
        return results[0] if results else None

    async def create_contact(
        self,
        name: str,
        company_id: str,
        campaign_id: str,
        job_title: str = "",
        email_addr: str = "",
        email_verified: bool = False,
        phone: str = "",
        linkedin_url: str = "",
        body_blocks: list[dict] | None = None,
    ) -> dict | None:
        """
        Create a contact with dedup logic.

        If a contact with the same email already exists, creation is
        skipped (returns None).

        Args:
            name: Contact full name (title).
            company_id: Page ID of the related company.
            campaign_id: Page ID of the related campaign.
            job_title: Contact's job title.
            email_addr: Contact's email address.
            email_verified: Whether the email has been verified.
            phone: Contact's phone number.
            linkedin_url: Contact's LinkedIn profile URL.
            body_blocks: Optional page body blocks with full details.

        Returns:
            The created page object, or None if skipped due to dedup.
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

        properties: dict = {
            "Name": title_prop(name),
            "Job Title": rich_text_prop(job_title),
            "Status": select_prop("Found"),
            "Company": relation_prop([company_id]),
            "Campaign": relation_prop([campaign_id]),
        }

        if email_addr:
            properties["Email"] = email_prop(email_addr)
        if email_verified:
            properties["Email Verified"] = checkbox_prop(True)
        if phone:
            properties["Phone"] = phone_prop(phone)
        if linkedin_url:
            properties["LinkedIn URL"] = url_prop(linkedin_url)

        result = await self._client.create_page(
            self._db_id, properties, body_blocks=body_blocks
        )
        logger.info("Created contact: %s (%s)", name, result["id"])
        return result

    async def update_contact(self, page_id: str, properties: dict) -> dict:
        """
        Update properties on an existing contact page.

        Args:
            page_id: The Notion page UUID of the contact.
            properties: Property values to update.

        Returns:
            The updated page object.
        """
        return await self._client.update_page(page_id, properties)

    async def get_contacts_for_company(self, company_id: str) -> list[dict]:
        """
        Fetch all contacts linked to a specific company.

        Args:
            company_id: The page UUID of the company.

        Returns:
            List of contact page objects linked to the company.
        """
        filter_obj = {
            "property": "Company",
            "relation": {"contains": company_id},
        }
        return await self._client.query_database(self._db_id, filter_obj=filter_obj)

    async def get_contacts_needing_emails(self) -> list[dict]:
        """
        Fetch all contacts with Status = Enriched (ready for email gen).

        Returns:
            List of contact page objects that need emails generated.
        """
        filter_obj = {
            "property": "Status",
            "select": {"equals": "Enriched"},
        }
        return await self._client.query_database(self._db_id, filter_obj=filter_obj)
