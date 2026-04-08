"""
Typed CRUD operations for the Campaigns Notion database.

Schema:
    Name (title), Target Description (rich_text), Status (select),
    Base Context (rich_text), Created At (date)
"""

import logging

from src.config import get_config
from src.notion.client import NotionClient
from src.notion.prop_helpers import (
    title_prop,
    rich_text_prop,
    select_prop,
    date_prop,
)

logger = logging.getLogger(__name__)

# Valid status values for campaigns
CAMPAIGN_STATUSES = ("Active", "Paused", "Completed")


class CampaignsDB:
    """
    Typed operations for the Campaigns database.

    Provides methods to list, create, and update campaign pages.
    """

    def __init__(self, client: NotionClient) -> None:
        """
        Initialise with a NotionClient instance.

        Args:
            client: The shared NotionClient to use for API calls.
        """
        self._client = client
        self._db_id = get_config().notion_campaigns_db_id

    @property
    def db_id(self) -> str:
        """Return the campaigns database ID from config."""
        return self._db_id

    @db_id.setter
    def db_id(self, value: str) -> None:
        """Allow overriding the database ID (used during setup)."""
        self._db_id = value

    async def get_active_campaigns(self) -> list[dict]:
        """
        Fetch all campaigns with Status = Active.

        Returns:
            List of Notion page objects for active campaigns.
        """
        filter_obj = {
            "property": "Status",
            "select": {"equals": "Active"},
        }
        return await self._client.query_database(self._db_id, filter_obj=filter_obj)

    async def create_campaign(
        self,
        name: str,
        target_description: str = "",
        base_context: str = "",
        status: str = "Active",
    ) -> dict:
        """
        Create a new campaign page.

        Args:
            name: Campaign name (title).
            target_description: Description of the target audience.
            base_context: Base context for email generation.
            status: Initial status (Active, Paused, or Completed).

        Returns:
            The created page object.
        """
        if status not in CAMPAIGN_STATUSES:
            logger.warning(
                "Invalid campaign status '%s', defaulting to Active", status
            )
            status = "Active"

        properties = {
            "Name": title_prop(name),
            "Target Description": rich_text_prop(target_description),
            "Status": select_prop(status),
            "Base Context": rich_text_prop(base_context),
            "Created At": date_prop(),
        }
        result = await self._client.create_page(self._db_id, properties)
        logger.info("Created campaign: %s (%s)", name, result["id"])
        return result

    async def update_status(self, page_id: str, status: str) -> dict:
        """
        Update the status of an existing campaign.

        Args:
            page_id: The Notion page UUID of the campaign.
            status: New status value (Active, Paused, or Completed).

        Returns:
            The updated page object.
        """
        if status not in CAMPAIGN_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {CAMPAIGN_STATUSES}"
            )

        properties = {"Status": select_prop(status)}
        return await self._client.update_page(page_id, properties)

    async def get_all(self) -> list[dict]:
        """
        Fetch all campaigns regardless of status.

        Returns:
            List of all campaign page objects.
        """
        return await self._client.query_database(self._db_id)

    async def find_by_name(self, name: str) -> dict | None:
        """
        Find a campaign by exact name match.

        Args:
            name: The campaign name to search for.

        Returns:
            The matching page object, or None if not found.
        """
        filter_obj = {
            "property": "Name",
            "title": {"equals": name},
        }
        results = await self._client.query_database(
            self._db_id, filter_obj=filter_obj
        )
        if results:
            return results[0]
        return None
