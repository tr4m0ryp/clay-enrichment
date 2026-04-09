"""
Stats computation and table update logic for the campaign dashboard.

Queries all four Notion databases (campaigns, companies, contacts, emails)
and computes per-campaign metrics. Writes results into a simple table block
on the dashboard page.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from src.notion.client import NotionClient
from src.notion.databases_campaigns import CampaignsDB
from src.notion.databases_companies import CompaniesDB
from src.notion.databases_contact_campaigns import ContactCampaignsDB
from src.notion.databases_contacts import ContactsDB
from src.notion.databases_emails import EmailsDB
from src.notion.prop_helpers import extract_title, extract_select

logger = logging.getLogger(__name__)


@dataclass
class CampaignStats:
    """Per-campaign statistics for dashboard display."""

    campaign_name: str
    campaign_id: str
    status: str
    companies_count: int
    contacts_count: int
    usable_contacts_count: int
    emails_pending_count: int
    emails_sent_count: int
    last_updated: str


async def _count_by_filter(
    client: NotionClient,
    db_id: str,
    filter_obj: dict,
) -> int:
    """Query a database with a filter and return the result count."""
    results = await client.query_database(db_id, filter_obj=filter_obj)
    return len(results)


async def _count_high_priority_leads(
    client: NotionClient,
    contact_campaigns_db_id: str,
    campaign_id: str,
    min_score: float = 7.0,
) -> int:
    """Count high-priority leads (junction entries with scores >= min_score)."""
    filter_obj = {
        "and": [
            {"property": "Campaign", "relation": {"contains": campaign_id}},
            {"property": "Relevance Score",
             "number": {"greater_than_or_equal_to": min_score}},
            {"property": "Company Fit Score",
             "number": {"greater_than_or_equal_to": min_score}},
        ]
    }
    results = await client.query_database(contact_campaigns_db_id, filter_obj=filter_obj)
    return len(results)


async def _compute_single_campaign(
    client: NotionClient,
    campaign_page: dict,
    companies_db_id: str,
    contacts_db_id: str,
    emails_db_id: str,
    contact_campaigns_db_id: str,
) -> CampaignStats:
    """Compute stats for a single campaign by querying related databases."""
    campaign_id = campaign_page["id"]
    campaign_name = extract_title(campaign_page, "Name")
    status = extract_select(campaign_page, "Status") or "Unknown"

    campaign_filter = {
        "property": "Campaign",
        "relation": {"contains": campaign_id},
    }

    # Run independent counts concurrently
    companies_count, contacts_count, usable_count, pending_count, sent_count = (
        await asyncio.gather(
            _count_by_filter(client, companies_db_id, campaign_filter),
            _count_by_filter(client, contacts_db_id, campaign_filter),
            _count_high_priority_leads(client, contact_campaigns_db_id, campaign_id),
            _count_by_filter(
                client,
                emails_db_id,
                {
                    "and": [
                        {
                            "property": "Campaign",
                            "relation": {"contains": campaign_id},
                        },
                        {
                            "property": "Status",
                            "select": {"equals": "Pending Review"},
                        },
                    ]
                },
            ),
            _count_by_filter(
                client,
                emails_db_id,
                {
                    "and": [
                        {
                            "property": "Campaign",
                            "relation": {"contains": campaign_id},
                        },
                        {
                            "property": "Status",
                            "select": {"equals": "Sent"},
                        },
                    ]
                },
            ),
        )
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    return CampaignStats(
        campaign_name=campaign_name,
        campaign_id=campaign_id,
        status=status,
        companies_count=companies_count,
        contacts_count=contacts_count,
        usable_contacts_count=usable_count,
        emails_pending_count=pending_count,
        emails_sent_count=sent_count,
        last_updated=now,
    )


async def compute_stats(
    campaigns_db: CampaignsDB,
    companies_db: CompaniesDB,
    contacts_db: ContactsDB,
    emails_db: EmailsDB,
    contact_campaigns_db: ContactCampaignsDB | None = None,
) -> list[CampaignStats]:
    """
    Query all databases and compute per-campaign metrics.

    Fetches every campaign, then for each one counts related companies,
    contacts, high-priority leads, pending emails, and sent emails.

    Args:
        campaigns_db: CampaignsDB instance.
        companies_db: CompaniesDB instance.
        contacts_db: ContactsDB instance.
        emails_db: EmailsDB instance.
        contact_campaigns_db: ContactCampaignsDB instance for lead counts.

    Returns:
        List of CampaignStats, one per campaign.
    """
    all_campaigns = await campaigns_db.get_all()
    campaigns = [c for c in all_campaigns if extract_select(c, "Status")]
    if not campaigns:
        logger.info("No campaigns found, returning empty stats")
        return []

    logger.info("Computing stats for %d campaigns", len(campaigns))

    client = campaigns_db._client
    cc_db_id = contact_campaigns_db.db_id if contact_campaigns_db else ""

    tasks = [
        _compute_single_campaign(
            client,
            campaign,
            companies_db.db_id,
            contacts_db.db_id,
            emails_db.db_id,
            cc_db_id,
        )
        for campaign in campaigns
    ]
    stats = await asyncio.gather(*tasks)
    return list(stats)


def _build_table_row(stat: CampaignStats) -> dict:
    """Build a Notion table_row block from a CampaignStats instance."""

    def cell(text: str) -> list[dict]:
        return [{"type": "text", "text": {"content": text}}]

    return {
        "type": "table_row",
        "table_row": {
            "cells": [
                cell(stat.campaign_name),
                cell(stat.status),
                cell(str(stat.companies_count)),
                cell(str(stat.contacts_count)),
                cell(str(stat.usable_contacts_count)),
                cell(str(stat.emails_pending_count)),
                cell(str(stat.emails_sent_count)),
                cell(stat.last_updated),
            ]
        },
    }


async def _delete_block(client: NotionClient, block_id: str) -> None:
    """Delete a single block by ID via the Notion SDK."""
    await client._call(client._sdk.blocks.delete, block_id=block_id)


async def update_stats_table(
    client: NotionClient,
    stats: list[CampaignStats],
    stats_table_id: str,
) -> None:
    """
    Replace the stats table content with fresh data.

    Deletes all non-header rows from the table block, then appends new
    rows with current stats. If the table block no longer exists (e.g.
    deleted manually), logs a warning and returns without error.

    Args:
        client: NotionClient instance.
        stats: List of CampaignStats to write.
        stats_table_id: Block ID of the simple_table block on the dashboard.
    """
    # Verify the table block exists
    try:
        children = await client.get_page_body(stats_table_id)
    except Exception as exc:
        logger.warning(
            "Stats table block %s not accessible, skipping update: %s",
            stats_table_id,
            exc,
        )
        return

    # Delete existing data rows (skip the first row which is the header)
    data_rows = [
        block for block in children
        if block.get("type") == "table_row"
    ]
    # The first table_row is the header; delete the rest
    rows_to_delete = data_rows[1:] if len(data_rows) > 1 else []

    if rows_to_delete:
        delete_tasks = [
            _delete_block(client, row["id"]) for row in rows_to_delete
        ]
        await asyncio.gather(*delete_tasks)
        logger.debug("Deleted %d old data rows from stats table", len(rows_to_delete))

    # Build and append new rows
    if not stats:
        logger.info("No campaign stats to write")
        return

    new_rows = [_build_table_row(stat) for stat in stats]
    await client.append_page_body(stats_table_id, new_rows)
    logger.info("Updated stats table with %d campaign rows", len(new_rows))
