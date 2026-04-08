"""
Typed CRUD operations for the Emails Notion database.

Schema:
    Subject (title), Contact (relation->Contacts),
    Status (select), Sender Address (rich_text),
    Sent At (date), Campaign (relation->Campaigns),
    Bounce (checkbox)
"""

import logging

from src.config import get_config
from src.notion.client import NotionClient
from src.notion.prop_helpers import (
    title_prop,
    rich_text_prop,
    select_prop,
    date_prop,
    checkbox_prop,
    relation_prop,
)

logger = logging.getLogger(__name__)

EMAIL_STATUSES = ("Pending Review", "Approved", "Sent", "Rejected", "Failed")


class EmailsDB:
    """
    Typed operations for the Emails database.

    Manages email drafts, approvals, and sending status tracking.
    """

    def __init__(self, client: NotionClient) -> None:
        """
        Initialise with a NotionClient instance.

        Args:
            client: The shared NotionClient to use for API calls.
        """
        self._client = client
        self._db_id = get_config().notion_emails_db_id

    @property
    def db_id(self) -> str:
        """Return the emails database ID from config."""
        return self._db_id

    @db_id.setter
    def db_id(self, value: str) -> None:
        """Allow overriding the database ID (used during setup)."""
        self._db_id = value

    async def create_email(
        self,
        subject: str,
        contact_id: str,
        campaign_id: str,
        sender_address: str = "",
        body_blocks: list[dict] | None = None,
    ) -> dict:
        """
        Create a new email draft page.

        The email is created with status 'Pending Review'. The full
        email body is stored as page body blocks, not in properties.

        Args:
            subject: Email subject line (title).
            contact_id: Page ID of the related contact.
            campaign_id: Page ID of the related campaign.
            sender_address: The sender email address to use.
            body_blocks: Page body blocks containing the email content.

        Returns:
            The created page object.
        """
        properties = {
            "Subject": title_prop(subject),
            "Contact": relation_prop([contact_id]),
            "Campaign": relation_prop([campaign_id]),
            "Status": select_prop("Pending Review"),
            "Bounce": checkbox_prop(False),
        }

        if sender_address:
            properties["Sender Address"] = rich_text_prop(sender_address)

        result = await self._client.create_page(
            self._db_id, properties, body_blocks=body_blocks
        )
        logger.info("Created email draft: %s (%s)", subject, result["id"])
        return result

    async def update_status(self, page_id: str, status: str) -> dict:
        """
        Update the status of an email.

        Args:
            page_id: The Notion page UUID of the email.
            status: New status value.

        Returns:
            The updated page object.

        Raises:
            ValueError: If the status is not a valid option.
        """
        if status not in EMAIL_STATUSES:
            raise ValueError(
                f"Invalid email status '{status}'. Must be one of: {EMAIL_STATUSES}"
            )

        properties: dict = {"Status": select_prop(status)}

        if status == "Sent":
            properties["Sent At"] = date_prop()

        return await self._client.update_page(page_id, properties)

    async def mark_bounced(self, page_id: str) -> dict:
        """
        Mark an email as bounced and set status to Failed.

        Args:
            page_id: The Notion page UUID of the email.

        Returns:
            The updated page object.
        """
        properties = {
            "Bounce": checkbox_prop(True),
            "Status": select_prop("Failed"),
        }
        return await self._client.update_page(page_id, properties)

    async def get_pending_review(self) -> list[dict]:
        """
        Fetch all emails with Status = Pending Review.

        Returns:
            List of email page objects awaiting review.
        """
        filter_obj = {
            "property": "Status",
            "select": {"equals": "Pending Review"},
        }
        return await self._client.query_database(self._db_id, filter_obj=filter_obj)

    async def get_approved_emails(self) -> list[dict]:
        """
        Fetch all emails with Status = Approved (ready to send).

        Returns:
            List of email page objects approved for sending.
        """
        filter_obj = {
            "property": "Status",
            "select": {"equals": "Approved"},
        }
        return await self._client.query_database(self._db_id, filter_obj=filter_obj)

    async def get_emails_for_campaign(self, campaign_id: str) -> list[dict]:
        """
        Fetch all emails linked to a specific campaign.

        Args:
            campaign_id: The page UUID of the campaign.

        Returns:
            List of email page objects for the campaign.
        """
        filter_obj = {
            "property": "Campaign",
            "relation": {"contains": campaign_id},
        }
        return await self._client.query_database(self._db_id, filter_obj=filter_obj)
