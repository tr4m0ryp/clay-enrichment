"""
Dashboard stats logging worker.

Periodic async loop that computes per-campaign statistics via SQL
count queries and logs them. The Notion dashboard block update logic
has been removed -- the Next.js frontend replaces it.
"""

import asyncio
import logging

import asyncpg

from src.db.campaigns import CampaignsDB

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 300  # 5 minutes


async def _compute_stats(
    pool: asyncpg.Pool, campaigns: list[dict]
) -> list[dict]:
    """Compute per-campaign statistics via SQL count queries.

    Args:
        pool: asyncpg connection pool.
        campaigns: List of campaign dicts.

    Returns:
        List of stat dicts, one per campaign.
    """
    stats = []
    for campaign in campaigns:
        cid = campaign["id"]
        cname = campaign.get("name", "")

        companies = await pool.fetchval(
            "SELECT COUNT(*) FROM company_campaigns WHERE campaign_id = $1",
            cid,
        )
        contacts = await pool.fetchval(
            "SELECT COUNT(*) FROM contact_campaign_links WHERE campaign_id = $1",
            cid,
        )
        high_priority = await pool.fetchval(
            "SELECT COUNT(*) FROM contact_campaigns "
            "WHERE campaign_id = $1 AND relevance_score >= 7 "
            "AND company_fit_score >= 7",
            cid,
        )
        emails_pending = await pool.fetchval(
            "SELECT COUNT(*) FROM emails "
            "WHERE campaign_id = $1 AND status = 'Pending Review'",
            cid,
        )
        emails_sent = await pool.fetchval(
            "SELECT COUNT(*) FROM emails "
            "WHERE campaign_id = $1 AND status = 'Sent'",
            cid,
        )

        stats.append({
            "campaign_name": cname,
            "campaign_id": str(cid),
            "companies": companies,
            "contacts": contacts,
            "high_priority": high_priority,
            "emails_pending": emails_pending,
            "emails_sent": emails_sent,
        })

    return stats


async def dashboard_stats_worker(
    pool: asyncpg.Pool,
    campaigns_db: CampaignsDB,
) -> None:
    """Continuous loop that logs dashboard stats every 5 minutes.

    Stats are computed via SQL queries. The Next.js frontend handles
    the actual dashboard UI -- this worker only logs for observability.

    Args:
        pool: asyncpg connection pool for raw count queries.
        campaigns_db: CampaignsDB instance for fetching campaign list.
    """
    while True:
        try:
            campaigns = await campaigns_db.get_all()
            if not campaigns:
                logger.debug("No campaigns found for stats")
                await asyncio.sleep(REFRESH_INTERVAL)
                continue

            stats = await _compute_stats(pool, campaigns)

            for s in stats:
                logger.info(
                    "Stats [%s]: companies=%d contacts=%d "
                    "high_priority=%d emails_pending=%d emails_sent=%d",
                    s["campaign_name"],
                    s["companies"],
                    s["contacts"],
                    s["high_priority"],
                    s["emails_pending"],
                    s["emails_sent"],
                )

            logger.info(
                "Dashboard stats refreshed: %d campaigns", len(stats)
            )
        except Exception:
            logger.exception(
                "Dashboard stats refresh failed, will retry next cycle"
            )

        await asyncio.sleep(REFRESH_INTERVAL)
