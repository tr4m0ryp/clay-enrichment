"""
Typed CRUD operations for the Companies Notion database.

Schema:
    Name (title), Website (url), Industry (select), Location (rich_text),
    Size (rich_text), DPP Fit Score (number), Status (select),
    Campaign (relation->Campaigns), Source Query (rich_text),
    Last Enriched (date)
"""

import logging
from datetime import datetime, timezone, timedelta

from src.config import get_config
from src.notion.client import NotionClient
from src.notion.prop_helpers import (
    title_prop,
    rich_text_prop,
    select_prop,
    url_prop,
    relation_prop,
    extract_select,
    extract_date,
    extract_relation_ids,
)

logger = logging.getLogger(__name__)

COMPANY_STATUSES = (
    "Discovered",
    "Enriched",
    "Partially Enriched",
    "Contacts Found",
)

INDUSTRY_OPTIONS = ("Fashion", "Streetwear", "Lifestyle", "Other")


class CompaniesDB:
    """
    Typed operations for the Companies database.

    Includes dedup logic: before creating, checks for existing companies
    by name. If a match exists and is recently enriched, the create is
    skipped. If linked to a different campaign, the new campaign relation
    is appended.
    """

    def __init__(self, client: NotionClient) -> None:
        """
        Initialise with a NotionClient instance.

        Args:
            client: The shared NotionClient to use for API calls.
        """
        self._client = client
        self._db_id = get_config().notion_companies_db_id
        self._stale_days = get_config().enrichment_stale_days

    @property
    def db_id(self) -> str:
        """Return the companies database ID from config."""
        return self._db_id

    @db_id.setter
    def db_id(self, value: str) -> None:
        """Allow overriding the database ID (used during setup)."""
        self._db_id = value

    async def find_by_name(self, name: str) -> dict | None:
        """
        Find a company by exact name match.

        Args:
            name: The company name to search for.

        Returns:
            The first matching page object, or None if not found.
        """
        filter_obj = {
            "property": "Name",
            "title": {"equals": name},
        }
        results = await self._client.query_database(
            self._db_id, filter_obj=filter_obj
        )
        return results[0] if results else None

    async def find_by_domain(self, domain: str) -> dict | None:
        """
        Find a company by website domain (contains match).

        Args:
            domain: The domain string to search for (e.g. 'example.com').

        Returns:
            The first matching page object, or None if not found.
        """
        filter_obj = {
            "property": "Website",
            "url": {"contains": domain},
        }
        results = await self._client.query_database(
            self._db_id, filter_obj=filter_obj
        )
        return results[0] if results else None

    def _is_recently_enriched(self, page: dict) -> bool:
        """
        Check if a company page was enriched within the stale threshold.

        Args:
            page: A Notion page object.

        Returns:
            True if the company is enriched and within the stale window.
        """
        status = extract_select(page, "Status")
        if status != "Enriched":
            return False

        last_enriched = extract_date(page, "Last Enriched")
        if not last_enriched:
            return False

        try:
            enriched_dt = datetime.fromisoformat(last_enriched)
            if enriched_dt.tzinfo is None:
                enriched_dt = enriched_dt.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=self._stale_days)
            return enriched_dt > cutoff
        except (ValueError, TypeError):
            return False

    async def create_company(
        self,
        name: str,
        campaign_id: str,
        website: str = "",
        industry: str = "Other",
        location: str = "",
        size: str = "",
        source_query: str = "",
        body_blocks: list[dict] | None = None,
    ) -> dict | None:
        """
        Create a company, with dedup logic.

        If a company with the same name exists and is recently enriched,
        creation is skipped (returns None). If it exists but is linked to
        a different campaign, the new campaign relation is appended.

        Args:
            name: Company name (title).
            campaign_id: Page ID of the associated campaign.
            website: Company website URL.
            industry: Industry category.
            location: Location description.
            size: Company size description.
            source_query: The search query that found this company.
            body_blocks: Optional page body blocks with full details.

        Returns:
            The created or updated page object, or None if skipped.
        """
        existing = await self.find_by_name(name)
        if existing:
            if self._is_recently_enriched(existing):
                logger.info("Skipping company '%s': recently enriched", name)
                # Check if campaign needs linking
                existing_campaigns = extract_relation_ids(existing, "Campaign")
                if campaign_id not in existing_campaigns:
                    existing_campaigns.append(campaign_id)
                    await self._client.update_page(
                        existing["id"],
                        {"Campaign": relation_prop(existing_campaigns)},
                    )
                    logger.info("Linked campaign to existing company '%s'", name)
                return None

            # Exists but stale or not enriched -- update campaign link
            existing_campaigns = extract_relation_ids(existing, "Campaign")
            if campaign_id not in existing_campaigns:
                existing_campaigns.append(campaign_id)
                await self._client.update_page(
                    existing["id"],
                    {"Campaign": relation_prop(existing_campaigns)},
                )
            logger.info("Company '%s' exists but stale, returning for re-enrichment", name)
            return existing

        if industry not in INDUSTRY_OPTIONS:
            industry = "Other"

        properties = {
            "Name": title_prop(name),
            "Website": url_prop(website) if website else url_prop(""),
            "Industry": select_prop(industry),
            "Location": rich_text_prop(location),
            "Size": rich_text_prop(size),
            "Status": select_prop("Discovered"),
            "Campaign": relation_prop([campaign_id]),
            "Source Query": rich_text_prop(source_query),
        }
        result = await self._client.create_page(
            self._db_id, properties, body_blocks=body_blocks
        )
        logger.info("Created company: %s (%s)", name, result["id"])
        return result

    async def update_company(self, page_id: str, properties: dict) -> dict:
        """
        Update properties on an existing company page.

        Args:
            page_id: The Notion page UUID of the company.
            properties: Property values to update.

        Returns:
            The updated page object.
        """
        return await self._client.update_page(page_id, properties)

    async def get_companies_by_status(self, status: str) -> list[dict]:
        """
        Fetch all companies with a given status.

        Args:
            status: The status to filter by.

        Returns:
            List of matching company page objects.
        """
        filter_obj = {
            "property": "Status",
            "select": {"equals": status},
        }
        return await self._client.query_database(self._db_id, filter_obj=filter_obj)

    async def get_stale_companies(self, days: int | None = None) -> list[dict]:
        """
        Fetch companies that were last enriched more than N days ago
        or have never been enriched.

        Args:
            days: Override for the stale threshold. Defaults to config value.

        Returns:
            List of company page objects needing re-enrichment.
        """
        threshold = days or self._stale_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold)
        cutoff_str = cutoff.date().isoformat()

        filter_obj = {
            "or": [
                {
                    "property": "Last Enriched",
                    "date": {"before": cutoff_str},
                },
                {
                    "property": "Last Enriched",
                    "date": {"is_empty": True},
                },
            ]
        }
        return await self._client.query_database(self._db_id, filter_obj=filter_obj)
