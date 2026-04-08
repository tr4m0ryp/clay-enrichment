"""
Auto-create Notion databases in the hub page.

Creates all four databases (Campaigns, Companies, Contacts, Emails) with
correct schemas and inter-database relations. Idempotent: checks if DB
IDs are already configured before creating.

Run this module directly to set up databases:
    python -m src.notion.setup
"""

import asyncio
import logging

from src.config import get_config
from src.notion.client import NotionClient
from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


def _campaigns_schema() -> dict:
    """
    Return the property schema for the Campaigns database.

    Returns:
        Dict of property name to Notion property schema definition.
    """
    return {
        "Name": {"title": {}},
        "Target Description": {"rich_text": {}},
        "Status": {
            "select": {
                "options": [
                    {"name": "Active", "color": "green"},
                    {"name": "Paused", "color": "yellow"},
                    {"name": "Completed", "color": "gray"},
                ]
            }
        },
        "Base Context": {"rich_text": {}},
        "Created At": {"date": {}},
    }


def _companies_schema(campaigns_db_id: str) -> dict:
    """
    Return the property schema for the Companies database.

    Args:
        campaigns_db_id: The Campaigns database ID for the relation.

    Returns:
        Dict of property name to Notion property schema definition.
    """
    return {
        "Name": {"title": {}},
        "Website": {"url": {}},
        "Industry": {
            "select": {
                "options": [
                    {"name": "Fashion", "color": "pink"},
                    {"name": "Streetwear", "color": "purple"},
                    {"name": "Lifestyle", "color": "blue"},
                    {"name": "Other", "color": "gray"},
                ]
            }
        },
        "Location": {"rich_text": {}},
        "Size": {"rich_text": {}},
        "DPP Fit Score": {"number": {"format": "number"}},
        "Status": {
            "select": {
                "options": [
                    {"name": "Discovered", "color": "gray"},
                    {"name": "Enriched", "color": "green"},
                    {"name": "Partially Enriched", "color": "yellow"},
                    {"name": "Contacts Found", "color": "blue"},
                ]
            }
        },
        "Campaign": {
            "relation": {
                "database_id": campaigns_db_id,
                "single_property": {},
            }
        },
        "Source Query": {"rich_text": {}},
        "Last Enriched": {"date": {}},
    }


def _contacts_schema(companies_db_id: str, campaigns_db_id: str) -> dict:
    """
    Return the property schema for the Contacts database.

    Args:
        companies_db_id: The Companies database ID for the relation.
        campaigns_db_id: The Campaigns database ID for the relation.

    Returns:
        Dict of property name to Notion property schema definition.
    """
    return {
        "Name": {"title": {}},
        "Job Title": {"rich_text": {}},
        "Email": {"email": {}},
        "Email Verified": {"checkbox": {}},
        "Phone": {"phone_number": {}},
        "LinkedIn URL": {"url": {}},
        "Company": {
            "relation": {
                "database_id": companies_db_id,
                "single_property": {},
            }
        },
        "Status": {
            "select": {
                "options": [
                    {"name": "Found", "color": "gray"},
                    {"name": "Enriched", "color": "green"},
                    {"name": "Email Generated", "color": "blue"},
                ]
            }
        },
        "Campaign": {
            "relation": {
                "database_id": campaigns_db_id,
                "single_property": {},
            }
        },
    }


def _emails_schema(contacts_db_id: str, campaigns_db_id: str) -> dict:
    """
    Return the property schema for the Emails database.

    Args:
        contacts_db_id: The Contacts database ID for the relation.
        campaigns_db_id: The Campaigns database ID for the relation.

    Returns:
        Dict of property name to Notion property schema definition.
    """
    return {
        "Subject": {"title": {}},
        "Contact": {
            "relation": {
                "database_id": contacts_db_id,
                "single_property": {},
            }
        },
        "Status": {
            "select": {
                "options": [
                    {"name": "Pending Review", "color": "yellow"},
                    {"name": "Approved", "color": "green"},
                    {"name": "Sent", "color": "blue"},
                    {"name": "Rejected", "color": "red"},
                    {"name": "Failed", "color": "gray"},
                ]
            }
        },
        "Sender Address": {"rich_text": {}},
        "Sent At": {"date": {}},
        "Campaign": {
            "relation": {
                "database_id": campaigns_db_id,
                "single_property": {},
            }
        },
        "Bounce": {"checkbox": {}},
    }


async def setup_databases(client: NotionClient | None = None) -> dict[str, str]:
    """
    Create all four databases in the Notion hub page if not already set up.

    Databases are created in dependency order: Campaigns first, then
    Companies, Contacts, and Emails. Each subsequent database references
    the ones created before it via relation properties.

    Idempotent: if a database ID is already configured, that database
    is skipped.

    Args:
        client: Optional NotionClient instance. If None, one is created.

    Returns:
        Dict mapping database names to their IDs (both existing and new).
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
    }

    # Step 1: Campaigns (no dependencies)
    if not db_ids["campaigns"]:
        logger.info("Creating Campaigns database...")
        result = await client.create_database(
            hub_page_id, "Campaigns", _campaigns_schema()
        )
        db_ids["campaigns"] = result["id"]

    # Step 2: Companies (depends on Campaigns)
    if not db_ids["companies"]:
        logger.info("Creating Companies database...")
        result = await client.create_database(
            hub_page_id, "Companies", _companies_schema(db_ids["campaigns"])
        )
        db_ids["companies"] = result["id"]

    # Step 3: Contacts (depends on Companies, Campaigns)
    if not db_ids["contacts"]:
        logger.info("Creating Contacts database...")
        result = await client.create_database(
            hub_page_id,
            "Contacts",
            _contacts_schema(db_ids["companies"], db_ids["campaigns"]),
        )
        db_ids["contacts"] = result["id"]

    # Step 4: Emails (depends on Contacts, Campaigns)
    if not db_ids["emails"]:
        logger.info("Creating Emails database...")
        result = await client.create_database(
            hub_page_id,
            "Emails",
            _emails_schema(db_ids["contacts"], db_ids["campaigns"]),
        )
        db_ids["emails"] = result["id"]

    _print_db_ids(db_ids)
    return db_ids


def _print_db_ids(db_ids: dict[str, str]) -> None:
    """
    Print the database IDs for the user to add to .env.

    Args:
        db_ids: Mapping of database names to their Notion UUIDs.
    """
    print("\n--- Notion Database IDs ---")
    print("Add these to your .env file:\n")
    print(f"NOTION_CAMPAIGNS_DB_ID={db_ids['campaigns']}")
    print(f"NOTION_COMPANIES_DB_ID={db_ids['companies']}")
    print(f"NOTION_CONTACTS_DB_ID={db_ids['contacts']}")
    print(f"NOTION_EMAILS_DB_ID={db_ids['emails']}")
    print("---\n")


if __name__ == "__main__":
    from src.utils.logger import setup_logging

    setup_logging()
    asyncio.run(setup_databases())
