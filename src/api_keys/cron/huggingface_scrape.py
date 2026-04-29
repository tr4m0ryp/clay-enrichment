"""Cron entrypoint: scrape Hugging Face Spaces.

Runs every 10 min via systemd timer, independent of the GitHub /
GitLab scrapes. Discovers Gemini-themed public Spaces, walks each
Space's repo tree, fetches likely key-bearing files (.env, app.py,
config.*, README), and pushes any extracted candidates into the same
producer/consumer pipeline (insert + validate + upsert).

Run as: ``python -m src.api_keys.cron.huggingface_scrape``
Optional: ``HF_TOKEN`` env var (raises rate limit ~50x).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import asyncpg
import httpx

from src.api_keys.database import (
    append_log,
    insert_potential_key,
    update_potential_key_status,
    update_system_status,
    upsert_validated_key,
)
from src.api_keys.scraper.huggingface import scrape_huggingface_keys
from src.api_keys.supabase_client import close_supabase_pool, get_supabase_pool
from src.api_keys.types import ScrapeProgress
from src.api_keys.validator import validate_gemini_key
from src.utils.logger import get_logger


logger = get_logger(__name__)
SERVICE = "huggingface_scraper"
_DONE = object()
_VALIDATION_CONCURRENCY = 5
_QUEUE_MAXSIZE = 100


async def _consumer(
    db_pool: asyncpg.Pool, queue: asyncio.Queue, progress: ScrapeProgress
) -> None:
    """Insert + validate + upsert each candidate as it arrives."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            item = await queue.get()
            try:
                if item is _DONE:
                    return
                try:
                    potential_id = await insert_potential_key(db_pool, item)
                except Exception as exc:  # noqa: BLE001
                    logger.error("hf stream-insert failed: %s", exc)
                    continue
                if potential_id is None:
                    continue
                try:
                    result = await validate_gemini_key(item.key, client=client)
                    await upsert_validated_key(db_pool, potential_id, result)
                    await update_potential_key_status(
                        db_pool, potential_id, result.status
                    )
                    progress.validated += 1
                except Exception as exc:  # noqa: BLE001
                    progress.validation_errors += 1
                    logger.error("hf validate failed: %s", exc)
            finally:
                queue.task_done()


async def _run(pool: asyncpg.Pool, execution_id: uuid.UUID) -> dict:
    progress = ScrapeProgress(total=0, current_source="huggingface.co")
    seen_keys: set[str] = set()
    results = []
    queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    consumers = [
        asyncio.create_task(_consumer(pool, queue, progress))
        for _ in range(_VALIDATION_CONCURRENCY)
    ]
    try:
        await scrape_huggingface_keys(
            queries=[],
            seen_keys=seen_keys,
            progress=progress,
            on_progress=None,
            results=results,
            limit=0,
            out_queue=queue,
        )
    finally:
        for _ in consumers:
            await queue.put(_DONE)
        await asyncio.gather(*consumers, return_exceptions=True)
    return {
        "scraped": len(results),
        "validated": progress.validated,
        "errors": progress.validation_errors,
    }


async def main() -> int:
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
            pool, SERVICE, state="completed",
            last_stats=stats, last_error=None,
        )
        await append_log(
            pool, SERVICE, "success", f"{SERVICE} completed",
            meta=stats, execution_id=execution_id,
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
