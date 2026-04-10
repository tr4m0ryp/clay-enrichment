"""One-time script to archive all records in Companies, Contacts,
Contact-Campaigns, and Emails databases.

Run after implementing the redesigned pipeline to clear stale data
gathered under the old logic (hardcoded CEO searches, no DPP score
gating, no Context property, old email format).

Safe: archives pages (sets archived=true), does not permanently delete.
Notion retains archived pages and they can be restored manually.

Usage:
    python -m scripts.clear_databases

Requires NOTION_API_KEY and database IDs in .env.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from src.config import get_config
from src.notion.client import NotionClient
from src.utils.logger import get_logger

logger = get_logger("clear_databases")

_CONCURRENCY = 5  # parallel archive requests per database


async def _archive_all_in_database(
    client: NotionClient, db_id: str, db_name: str
) -> int:
    """Archive every page in a Notion database.

    Args:
        client: The shared NotionClient.
        db_id: The Notion database UUID.
        db_name: Human-readable name for logging.

    Returns:
        Count of pages archived (including failures that logged errors).
    """
    if not db_id:
        logger.warning("Skipping '%s': no database ID configured", db_name)
        return 0

    logger.info("Querying '%s' database (%s)...", db_name, db_id[:8])
    try:
        pages = await client.query_database(db_id)
    except Exception as exc:
        logger.error("Failed to query '%s': %s", db_name, exc)
        return 0

    if not pages:
        logger.info("'%s' is already empty", db_name)
        return 0

    logger.info("'%s' has %d active page(s) to archive", db_name, len(pages))

    sem = asyncio.Semaphore(_CONCURRENCY)
    archived_count = 0
    failed_count = 0

    async def _archive_one(page_id: str) -> None:
        nonlocal archived_count, failed_count
        async with sem:
            try:
                await client._call(
                    client._sdk.pages.update,
                    page_id=page_id,
                    archived=True,
                )
                archived_count += 1
                logger.debug("Archived %s page %s", db_name, page_id[:8])
            except Exception as exc:
                failed_count += 1
                logger.error(
                    "Failed to archive %s page %s: %s",
                    db_name, page_id[:8], exc,
                )

    await asyncio.gather(*[_archive_one(p["id"]) for p in pages])

    logger.info(
        "'%s': archived=%d failed=%d (of %d total)",
        db_name, archived_count, failed_count, len(pages),
    )
    return archived_count


async def _count_pages(
    client: NotionClient, db_id: str, db_name: str
) -> int:
    """Return the count of active (non-archived) pages in a database."""
    if not db_id:
        return 0
    try:
        pages = await client.query_database(db_id)
        return len(pages)
    except Exception as exc:
        logger.error("Failed to count '%s': %s", db_name, exc)
        return 0


async def main() -> None:
    """Query all databases, show counts, confirm, then archive."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = get_config()
    if not config.notion_api_key:
        logger.error("NOTION_API_KEY is not set. Aborting.")
        sys.exit(1)

    targets = [
        ("Companies", config.notion_companies_db_id),
        ("Contacts", config.notion_contacts_db_id),
        ("Contact-Campaigns", config.notion_contact_campaigns_db_id),
        ("Emails", config.notion_emails_db_id),
    ]

    client = NotionClient()

    # Step 1: Show counts before archiving
    print("")
    print("=" * 60)
    print("Database cleanup: current active page counts")
    print("=" * 60)
    counts = {}
    total = 0
    for name, db_id in targets:
        count = await _count_pages(client, db_id, name)
        counts[name] = count
        total += count
        status = "(no ID configured)" if not db_id else ""
        print(f"  {name:<20} {count:>6} page(s)  {status}")
    print("-" * 60)
    print(f"  {'TOTAL':<20} {total:>6} page(s)")
    print("=" * 60)
    print("")

    if total == 0:
        print("All target databases are already empty. Nothing to do.")
        return

    # Step 2: Require explicit confirmation
    print(
        "This will archive (not delete) every active page in the "
        "databases above."
    )
    print(
        "Archived pages are retained by Notion and can be restored "
        "via the Notion UI."
    )
    print("")
    confirmation = input("Type 'YES' to proceed: ").strip()
    if confirmation != "YES":
        print("Aborted. No pages were archived.")
        return

    # Step 3: Archive each database
    print("")
    print("Archiving pages...")
    print("")
    results: dict[str, int] = {}
    for name, db_id in targets:
        results[name] = await _archive_all_in_database(client, db_id, name)

    # Step 4: Final summary
    print("")
    print("=" * 60)
    print("Cleanup complete")
    print("=" * 60)
    grand_total = 0
    for name, _db_id in targets:
        archived = results.get(name, 0)
        grand_total += archived
        print(f"  {name:<20} archived {archived:>6} page(s)")
    print("-" * 60)
    print(f"  {'TOTAL':<20} archived {grand_total:>6} page(s)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
