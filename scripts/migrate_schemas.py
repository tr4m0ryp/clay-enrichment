"""One-time schema migration script.

Adds new properties introduced by the outreach hub pipeline redesign to
existing Notion databases that predate the schema change.

Changes applied:
- Contacts database: add "Context" (rich_text) property
- Contact-Campaigns junction database: add "Context" (rich_text) property
- Campaigns database: add "Abort" to Status select options

Removed properties (Company Size, Phone Number, Base Context) are NOT
removed from existing databases -- the Notion API does not support
property deletion via update. Leave them in place; they will simply
become stale orphan fields. Remove manually in the Notion UI if desired.

Usage:
    python -m scripts.migrate_schemas

Requires NOTION_API_KEY and database IDs in .env.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from src.config import get_config
from src.notion.client import NotionClient
from src.utils.logger import get_logger

logger = get_logger("migrate_schemas")


async def _add_property(
    client: NotionClient, db_id: str, db_name: str, prop_name: str, prop_def: dict
) -> bool:
    """Add a single property to an existing database schema.

    Returns True if added, False if already present or on error.
    """
    if not db_id:
        logger.warning("Skipping '%s': no database ID configured", db_name)
        return False

    try:
        db = await client._call(client._sdk.databases.retrieve, database_id=db_id)
    except Exception as exc:
        logger.error("Failed to fetch '%s' schema: %s", db_name, exc)
        return False

    if prop_name in db.get("properties", {}):
        logger.info("'%s' already has property '%s' -- skipping", db_name, prop_name)
        return False

    try:
        await client.update_database(db_id, {prop_name: prop_def})
        logger.info("'%s': added property '%s'", db_name, prop_name)
        return True
    except Exception as exc:
        logger.error("Failed to add '%s' to '%s': %s", prop_name, db_name, exc)
        return False


async def _add_status_option(
    client: NotionClient, db_id: str, db_name: str, prop_name: str, option_name: str
) -> bool:
    """Add a new option to an existing select property.

    Returns True if added, False if already present or on error.
    """
    if not db_id:
        logger.warning("Skipping '%s': no database ID configured", db_name)
        return False

    try:
        db = await client._call(client._sdk.databases.retrieve, database_id=db_id)
    except Exception as exc:
        logger.error("Failed to fetch '%s' schema: %s", db_name, exc)
        return False

    prop = db.get("properties", {}).get(prop_name)
    if not prop or prop.get("type") != "select":
        logger.warning("'%s' has no select property '%s'", db_name, prop_name)
        return False

    current = prop["select"].get("options", [])
    names = {opt["name"] for opt in current}
    if option_name in names:
        logger.info(
            "'%s.%s' already has option '%s' -- skipping",
            db_name, prop_name, option_name,
        )
        return False

    # Rebuild options preserving existing ones (required by Notion API)
    new_options = [{"name": opt["name"]} for opt in current]
    new_options.append({"name": option_name})

    try:
        await client.update_database(
            db_id,
            {prop_name: {"select": {"options": new_options}}},
        )
        logger.info("'%s.%s': added option '%s'", db_name, prop_name, option_name)
        return True
    except Exception as exc:
        logger.error(
            "Failed to add option '%s' to '%s.%s': %s",
            option_name, db_name, prop_name, exc,
        )
        return False


async def main() -> None:
    """Apply schema migrations to existing Notion databases."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = get_config()
    if not config.notion_api_key:
        logger.error("NOTION_API_KEY is not set. Aborting.")
        sys.exit(1)

    client = NotionClient()

    print("")
    print("=" * 60)
    print("Schema migration: adding new properties")
    print("=" * 60)
    print("")

    results: list[tuple[str, bool]] = []

    # 1. Contacts: add Context property
    added = await _add_property(
        client,
        config.notion_contacts_db_id,
        "Contacts",
        "Context",
        {"rich_text": {}},
    )
    results.append(("Contacts.Context", added))

    # 2. Contact-Campaigns junction: add Context property
    added = await _add_property(
        client,
        config.notion_contact_campaigns_db_id,
        "Contact-Campaigns",
        "Context",
        {"rich_text": {}},
    )
    results.append(("Contact-Campaigns.Context", added))

    # 3. Campaigns: add Abort status option
    added = await _add_status_option(
        client,
        config.notion_campaigns_db_id,
        "Campaigns",
        "Status",
        "Abort",
    )
    results.append(("Campaigns.Status.Abort", added))

    print("")
    print("=" * 60)
    print("Migration summary")
    print("=" * 60)
    for label, was_added in results:
        status = "added" if was_added else "skipped"
        print(f"  {label:<40} {status}")
    print("=" * 60)
    print("")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
