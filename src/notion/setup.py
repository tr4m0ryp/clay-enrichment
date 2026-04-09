"""
Auto-create Notion databases in the hub page.

Creates all databases (Campaigns, Companies, Contacts, Emails,
Contact-Campaigns) with correct schemas and inter-database relations,
plus the High Priority Leads parent page. Idempotent: checks if IDs
are already configured before creating.

Run this module directly to set up databases:
    python -m src.notion.setup
"""

import asyncio
import logging

import httpx

from src.config import get_config
from src.notion.client import NotionClient
from src.notion.databases_contact_campaigns_schema import contact_campaigns_schema
from src.notion.schemas import (
    campaigns_schema,
    companies_schema,
    contacts_schema,
    emails_schema,
)
from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_NOTION_API = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"


def _notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": _NOTION_VERSION,
    }


async def _create_page_under_page(
    api_key: str,
    parent_page_id: str,
    title: str,
    body_blocks: list[dict],
) -> dict:
    """
    Create a Notion page as a child of another page (not a database).

    Args:
        api_key: Notion integration API key.
        parent_page_id: UUID of the parent page.
        title: Page title text.
        body_blocks: List of block objects for the page body.

    Returns:
        The created page object (includes the new page ID).
    """
    body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
        "children": body_blocks,
    }
    resp = await asyncio.to_thread(
        httpx.post,
        f"{_NOTION_API}/pages",
        headers=_notion_headers(api_key),
        json=body,
    )
    resp.raise_for_status()
    result = resp.json()
    logger.info("_create_page_under_page: created '%s' -> %s", title, result["id"])
    return result


async def setup_databases(client: NotionClient | None = None) -> dict[str, str]:
    """
    Create all databases and the leads parent page if not already set up.

    Databases are created in dependency order: Campaigns first, then
    Companies, Contacts, Emails, and finally Contact-Campaigns (which
    depends on all three). The High Priority Leads page is created under
    the hub page.

    Idempotent: if an ID is already configured, that resource is skipped.

    Args:
        client: Optional NotionClient instance. If None, one is created.

    Returns:
        Dict mapping resource names to their IDs (both existing and new).
    """
    cfg = get_config()

    if client is None:
        limiter = RateLimiter()
        client = NotionClient(rate_limiter=limiter)

    hub_page_id = cfg.notion_hub_page_id
    if not hub_page_id:
        logger.error("NOTION_HUB_PAGE_ID is not set. Cannot create databases.")
        raise ValueError("NOTION_HUB_PAGE_ID must be set in .env")

    db_ids: dict[str, str] = {
        "campaigns": cfg.notion_campaigns_db_id,
        "companies": cfg.notion_companies_db_id,
        "contacts": cfg.notion_contacts_db_id,
        "emails": cfg.notion_emails_db_id,
        "contact_campaigns": cfg.notion_contact_campaigns_db_id,
        "leads_page": cfg.notion_leads_page_id,
    }

    # Step 1: Campaigns (no dependencies)
    if not db_ids["campaigns"]:
        logger.info("Creating Campaigns database...")
        result = await client.create_database(
            hub_page_id, "Campaigns", campaigns_schema()
        )
        db_ids["campaigns"] = result["id"]

    # Step 2: Companies (depends on Campaigns)
    if not db_ids["companies"]:
        logger.info("Creating Companies database...")
        result = await client.create_database(
            hub_page_id, "Companies", companies_schema(db_ids["campaigns"])
        )
        db_ids["companies"] = result["id"]

    # Step 3: Contacts (depends on Companies, Campaigns)
    if not db_ids["contacts"]:
        logger.info("Creating Contacts database...")
        result = await client.create_database(
            hub_page_id,
            "Contacts",
            contacts_schema(db_ids["companies"], db_ids["campaigns"]),
        )
        db_ids["contacts"] = result["id"]

    # Step 4: Emails (depends on Contacts, Campaigns)
    if not db_ids["emails"]:
        logger.info("Creating Emails database...")
        result = await client.create_database(
            hub_page_id,
            "Emails",
            emails_schema(db_ids["contacts"], db_ids["campaigns"]),
        )
        db_ids["emails"] = result["id"]

    # Step 5: Contact-Campaigns junction (depends on Contacts, Campaigns, Companies)
    if not db_ids["contact_campaigns"]:
        logger.info("Creating Contact-Campaigns junction database...")
        schema = contact_campaigns_schema(
            contacts_db_id=db_ids["contacts"],
            campaigns_db_id=db_ids["campaigns"],
            companies_db_id=db_ids["companies"],
        )
        result = await client.create_database(
            hub_page_id, "Contact Campaigns", schema
        )
        db_ids["contact_campaigns"] = result["id"]

    # Step 6: High Priority Leads parent page (under hub page)
    if not db_ids["leads_page"]:
        logger.info("Creating High Priority Leads page...")
        body_blocks = [
            {
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "Campaign Leads"}}
                    ]
                },
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "Select a campaign below to view high-priority contacts."
                            },
                        }
                    ]
                },
            },
        ]
        result = await _create_page_under_page(
            api_key=cfg.notion_api_key,
            parent_page_id=hub_page_id,
            title="High Priority Leads",
            body_blocks=body_blocks,
        )
        db_ids["leads_page"] = result["id"]

    _print_ids(db_ids)
    return db_ids


def _print_ids(db_ids: dict[str, str]) -> None:
    """
    Print resource IDs for the user to add to .env.

    Args:
        db_ids: Mapping of resource names to their Notion UUIDs.
    """
    print("\n--- Notion Resource IDs ---")
    print("Add these to your .env file:\n")
    print(f"NOTION_CAMPAIGNS_DB_ID={db_ids['campaigns']}")
    print(f"NOTION_COMPANIES_DB_ID={db_ids['companies']}")
    print(f"NOTION_CONTACTS_DB_ID={db_ids['contacts']}")
    print(f"NOTION_EMAILS_DB_ID={db_ids['emails']}")
    print(f"NOTION_CONTACT_CAMPAIGNS_DB_ID={db_ids['contact_campaigns']}")
    print(f"NOTION_LEADS_PAGE_ID={db_ids['leads_page']}")
    print("---\n")


if __name__ == "__main__":
    from src.utils.logger import setup_logging

    setup_logging()
    asyncio.run(setup_databases())
