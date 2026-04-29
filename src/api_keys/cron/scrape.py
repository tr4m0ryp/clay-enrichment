"""Cron entrypoint: scrape GitHub Code Search for Gemini keys.

Runs every 10 min via systemd timer. Calls scrape_github_keys with
store=True and validate=True so each new candidate is concurrently
stream-inserted into potential_keys and inline-validated into
validated_keys via the producer/consumer pipeline. Persists run state
to the ``scraper`` row in system_status and emits a log row to
key_pool_logs.

Run as: ``python -m src.api_keys.cron.scrape``
Tunable: ``CLAY_SCRAPE_LIMIT`` env var (default 0 = unlimited; positive
values cap unique candidates per run).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

from src.api_keys.database import append_log, update_system_status
from src.api_keys.scraper import scrape_github_keys
from src.api_keys.supabase_client import close_supabase_pool, get_supabase_pool
from src.utils.logger import get_logger


logger = get_logger(__name__)
SERVICE = "scraper"


async def _run(pool, execution_id: uuid.UUID) -> dict:
    """One scrape pass; returns stats for system_status / append_log."""
    # 0 means uncapped: run every static + dynamic query to exhaustion.
    limit = int(os.environ.get("CLAY_SCRAPE_LIMIT", "0"))
    results = await scrape_github_keys(
        limit=limit,
        store=True,
        validate=True,
    )
    return {"scraped": len(results)}


async def main() -> int:
    """Run one scrape pass, persist state, return process exit code."""
    pool = await get_supabase_pool()
    execution_id = uuid.uuid4()
    started = datetime.now(tz=timezone.utc)
    await update_system_status(
        pool,
        SERVICE,
        state="running",
        last_execution_id=execution_id,
        last_run_at=started,
    )
    try:
        stats = await _run(pool, execution_id)
        await update_system_status(
            pool,
            SERVICE,
            state="completed",
            last_stats=stats,
            last_error=None,
        )
        await append_log(
            pool,
            SERVICE,
            "success",
            f"{SERVICE} completed",
            meta=stats,
            execution_id=execution_id,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 -- top-level catch for systemd
        logger.exception(f"{SERVICE} failed")
        await update_system_status(
            pool, SERVICE, state="failed", last_error=str(exc)
        )
        await append_log(
            pool, SERVICE, "error", str(exc), execution_id=execution_id
        )
        return 1
    finally:
        await close_supabase_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
