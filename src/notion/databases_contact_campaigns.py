"""
Typed CRUD operations for the Contact-Campaign junction Notion database.

Schema:
    Name (title), Contact (relation->Contacts), Campaign (relation->Campaigns),
    Company (relation->Companies), Job Title (rich_text), Company Name (rich_text),
    Email (email), Email Verified (checkbox), Phone (phone_number),
    LinkedIn URL (url), Industry (select), Company Size (rich_text),
    Location (rich_text), Company Fit Score (number), Relevance Score (number),
    Score Reasoning (rich_text), Personalized Context (rich_text),
    Email Subject (rich_text), Outreach Status (select), Last Updated (date)

The schema function for setup.py lives in databases_contact_campaigns_schema.py.
"""

from __future__ import annotations

import logging

from src.notion.client import NotionClient
from src.notion.prop_helpers import (
    title_prop,
    rich_text_prop,
    select_prop,
    number_prop,
    url_prop,
    email_prop,
    phone_prop,
    checkbox_prop,
    date_prop,
    relation_prop,
)
from src.notion.databases_contact_campaigns_schema import (
    OUTREACH_STATUSES,
    INDUSTRY_OPTIONS,
    contact_campaigns_schema,  # re-exported for convenient single-module imports
)

logger = logging.getLogger(__name__)

__all__ = ["ContactCampaignsDB", "contact_campaigns_schema"]


class ContactCampaignsDB:
    """
    Typed operations for the Contact-Campaign junction database.

    Each record pairs one contact with one campaign, storing the
    campaign-specific relevance score, personalized context, and
    outreach status. Dedup is enforced by contact_id + campaign_id.
    """

    def __init__(self, client: NotionClient, db_id: str) -> None:
        """
        Initialise with a NotionClient and the junction database ID.

        Args:
            client: The shared NotionClient to use for API calls.
            db_id: The Notion database UUID for the junction table.
        """
        self._client = client
        self.db_id = db_id

    async def find_by_contact_campaign(
        self, contact_id: str, campaign_id: str
    ) -> dict | None:
        """
        Find an existing junction record for a contact + campaign pair.

        Args:
            contact_id: The Notion page UUID of the contact.
            campaign_id: The Notion page UUID of the campaign.

        Returns:
            The first matching page object, or None if not found.
        """
        filter_obj = {
            "and": [
                {"property": "Contact", "relation": {"contains": contact_id}},
                {"property": "Campaign", "relation": {"contains": campaign_id}},
            ]
        }
        results = await self._client.query_database(self.db_id, filter_obj=filter_obj)
        return results[0] if results else None

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
        phone: str = "",
        linkedin_url: str = "",
        industry: str = "Other",
        company_size: str = "",
        location: str = "",
        company_fit_score: float = 0,
        relevance_score: float = 0,
        score_reasoning: str = "",
        personalized_context: str = "",
        body_blocks: list[dict] | None = None,
    ) -> dict | None:
        """
        Create a junction record with dedup by contact_id + campaign_id.

        If a record for this pair already exists, creation is skipped (returns None).
        Denormalized fields are stored alongside relation pointers for fast display.
        """
        existing = await self.find_by_contact_campaign(contact_id, campaign_id)
        if existing:
            logger.info(
                "Skipping junction entry: contact '%s' + campaign '%s' already exists",
                contact_id,
                campaign_id,
            )
            return None

        if industry not in INDUSTRY_OPTIONS:
            industry = "Other"

        entry_name = f"{contact_name} - {campaign_name}"

        properties: dict = {
            "Name": title_prop(entry_name),
            "Contact": relation_prop([contact_id]),
            "Campaign": relation_prop([campaign_id]),
            "Company": relation_prop([company_id]),
            "Job Title": rich_text_prop(job_title),
            "Company Name": rich_text_prop(company_name),
            "Email Verified": checkbox_prop(email_verified),
            "Industry": select_prop(industry),
            "Company Size": rich_text_prop(company_size),
            "Location": rich_text_prop(location),
            "Company Fit Score": number_prop(company_fit_score),
            "Relevance Score": number_prop(relevance_score),
            "Score Reasoning": rich_text_prop(score_reasoning),
            "Personalized Context": rich_text_prop(personalized_context),
            "Outreach Status": select_prop("New"),
            "Last Updated": date_prop(),
        }

        if email_addr:
            properties["Email"] = email_prop(email_addr)
        if phone:
            properties["Phone"] = phone_prop(phone)
        if linkedin_url:
            properties["LinkedIn URL"] = url_prop(linkedin_url)

        result = await self._client.create_page(
            self.db_id, properties, body_blocks=body_blocks
        )
        logger.info("Created junction entry: %s (%s)", entry_name, result["id"])
        return result

    async def update_entry(self, page_id: str, properties: dict) -> dict:
        """
        Apply a partial property update to a junction record.

        Args:
            page_id: The Notion page UUID of the junction record.
            properties: Property values to update.

        Returns:
            The updated page object.
        """
        return await self._client.update_page(page_id, properties)

    async def update_score(
        self,
        page_id: str,
        relevance_score: float,
        score_reasoning: str,
        personalized_context: str,
    ) -> dict:
        """Update Relevance Score, Score Reasoning, and Personalized Context."""
        properties = {
            "Relevance Score": number_prop(relevance_score),
            "Score Reasoning": rich_text_prop(score_reasoning),
            "Personalized Context": rich_text_prop(personalized_context),
            "Last Updated": date_prop(),
        }
        return await self._client.update_page(page_id, properties)

    async def update_outreach_status(self, page_id: str, status: str) -> dict:
        """
        Update the outreach status. Raises ValueError for invalid values.

        Valid values: New, Email Pending Review, Email Approved, Sent, Replied,
        Meeting Booked.
        """
        if status not in OUTREACH_STATUSES:
            raise ValueError(
                f"Invalid outreach status '{status}'. "
                f"Must be one of: {', '.join(OUTREACH_STATUSES)}"
            )
        properties = {
            "Outreach Status": select_prop(status),
            "Last Updated": date_prop(),
        }
        return await self._client.update_page(page_id, properties)

    async def update_email_subject(self, page_id: str, subject: str) -> dict:
        """Update the Email Subject field after email generation."""
        properties = {
            "Email Subject": rich_text_prop(subject),
            "Last Updated": date_prop(),
        }
        return await self._client.update_page(page_id, properties)

    async def get_high_priority(
        self, campaign_id: str, min_score: float = 8.0
    ) -> list[dict]:
        """Return entries for campaign_id with Relevance Score >= min_score."""
        filter_obj = {
            "and": [
                {"property": "Campaign", "relation": {"contains": campaign_id}},
                {
                    "property": "Relevance Score",
                    "number": {"greater_than_or_equal_to": min_score},
                },
            ]
        }
        return await self._client.query_database(self.db_id, filter_obj=filter_obj)

    async def get_entries_for_campaign(self, campaign_id: str) -> list[dict]:
        """Return all junction entries for a campaign regardless of score."""
        filter_obj = {
            "property": "Campaign",
            "relation": {"contains": campaign_id},
        }
        return await self._client.query_database(self.db_id, filter_obj=filter_obj)

    async def get_unscored_entries(self, campaign_id: str) -> list[dict]:
        """Return entries for campaign_id where Relevance Score is 0 or empty."""
        filter_obj = {
            "and": [
                {"property": "Campaign", "relation": {"contains": campaign_id}},
                {
                    "or": [
                        {"property": "Relevance Score", "number": {"equals": 0}},
                        {"property": "Relevance Score", "number": {"is_empty": True}},
                    ]
                },
            ]
        }
        return await self._client.query_database(self.db_id, filter_obj=filter_obj)
