"""
Dashboard stats refresh worker.

Continuous async loop that reads the dashboard block IDs from the
persisted .dashboard_blocks.json file, computes per-campaign statistics
by querying all four Notion databases, and writes the results into
the stats table on the dashboard page every 5 minutes.
"""

import asyncio
import json
import logging
from pathlib import Path

from src.notion.databases_campaigns import CampaignsDB
from src.notion.databases_companies import CompaniesDB
from src.notion.databases_contacts import ContactsDB
from src.notion.databases_emails import EmailsDB
from src.notion.client import NotionClient
from src.notion.dashboard_stats import compute_stats, update_stats_table

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 300  # 5 minutes

_BLOCKS_FILE = Path(__file__).resolve().parents[2] / ".dashboard_blocks.json"


def _load_stats_table_id() -> str | None:
    """Read the stats_table_id from .dashboard_blocks.json.

    Returns:
        The stats table block ID, or None if the file is missing or invalid.
    """
    if not _BLOCKS_FILE.exists():
        logger.warning(
            "Dashboard blocks file not found at %s; "
            "stats refresh will be skipped this cycle",
            _BLOCKS_FILE,
        )
        return None

    try:
        data = json.loads(_BLOCKS_FILE.read_text())
        table_id = data.get("stats_table_id", "")
        if not table_id:
            logger.warning(
                "stats_table_id is empty in %s; "
                "dashboard may need to be rebuilt",
                _BLOCKS_FILE,
            )
            return None
        return table_id
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "Failed to read dashboard blocks file: %s", exc
        )
        return None


async def dashboard_stats_worker(
    notion_client: NotionClient,
    campaigns_db: CampaignsDB,
    companies_db: CompaniesDB,
    contacts_db: ContactsDB,
    emails_db: EmailsDB,
) -> None:
    """Continuous loop that refreshes dashboard stats every 5 minutes.

    Reads the stats table block ID from the persisted blocks file,
    computes fresh stats from all four databases, and updates the
    table. Errors are caught and logged so the loop continues.

    Args:
        notion_client: NotionClient instance for API calls.
        campaigns_db: CampaignsDB instance.
        companies_db: CompaniesDB instance.
        contacts_db: ContactsDB instance.
        emails_db: EmailsDB instance.
    """
    while True:
        try:
            stats_table_id = _load_stats_table_id()
            if stats_table_id is None:
                logger.warning(
                    "No stats table ID available, skipping refresh cycle"
                )
                await asyncio.sleep(REFRESH_INTERVAL)
                continue

            stats = await compute_stats(
                campaigns_db, companies_db, contacts_db, emails_db
            )

            await update_stats_table(notion_client, stats, stats_table_id)

            logger.info(
                "Dashboard stats refreshed: %d campaigns", len(stats)
            )
        except Exception:
            logger.exception(
                "Dashboard stats refresh failed, will retry next cycle"
            )

        await asyncio.sleep(REFRESH_INTERVAL)
