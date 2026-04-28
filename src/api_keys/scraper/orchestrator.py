"""Scrape orchestration: rotate queries, drive the per-query loop, persist.

Drives ``GitHubTokenPool`` against the GitHub Code Search API via
``_pages.scrape_one_query``, dedupes globally, and (optionally) batch-stores
plus inline-validates the results. The validator (Task 006) is imported
lazily inside the validate branch so this module loads even before that
task lands in the tree.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg
import httpx

from src.api_keys.database import (
    insert_potential_keys_batch,
    update_system_status,
)
from src.api_keys.github_token_pool import GitHubTokenPool
from src.api_keys.scraper._helpers import ProgressCallback, emit_progress
from src.api_keys.scraper._pages import (
    INTER_QUERY_SLEEP,
    LOG_PREVIEW_CHARS,
    scrape_one_query,
)
from src.api_keys.scraper.queries import build_all_queries
from src.api_keys.supabase_client import get_supabase_pool
from src.api_keys.types import ScrapedKey, ScrapeProgress
from src.utils.logger import get_logger


logger = get_logger(__name__)


async def _maybe_validate_inline(
    db_pool: asyncpg.Pool,
    results: list[ScrapedKey],
    progress: ScrapeProgress,
    on_progress: Optional[ProgressCallback],
    inserted_ids: dict[str, UUID],
) -> None:
    """Validate every scraped key inline; persist results when ids are known.

    Imports the validator lazily so this module loads even before Task 006
    lands. When the validator is missing the function logs and returns
    without raising, leaving callers free to retry once 006 ships.
    """
    try:
        from src.api_keys.validator import validate_gemini_key  # type: ignore
        from src.api_keys.database import upsert_validated_key
    except ImportError as exc:
        logger.warning(
            "inline validation requested but validator unavailable: %s",
            exc,
        )
        return
    for result in results:
        try:
            validation = await validate_gemini_key(result.key)
            potential_id = inserted_ids.get(result.key)
            if potential_id is not None:
                await upsert_validated_key(db_pool, potential_id, validation)
            progress.validated += 1
        except Exception as exc:  # noqa: BLE001 -- validator failures isolate
            progress.validation_errors += 1
            logger.error(
                "inline validation failed key_prefix=%s err=%s",
                result.key[:12],
                exc,
            )
        emit_progress(progress, on_progress)
        await asyncio.sleep(INTER_QUERY_SLEEP)


async def _persist_query_index(
    db_pool: asyncpg.Pool, start_index: int, processed: int, total: int
) -> None:
    """Persist the next-run starting index to system_status for ``scraper``."""
    if total <= 0:
        return
    next_index = (start_index + processed) % total
    try:
        await update_system_status(db_pool, "scraper", last_query_index=next_index)
    except Exception as exc:  # noqa: BLE001 -- bookkeeping must never abort
        logger.error("failed to persist last_query_index: %s", exc)


async def _lookup_potential_ids(
    db_pool: asyncpg.Pool, key_values: list[str]
) -> dict[str, UUID]:
    """Map ``key_value -> id`` for the supplied potential keys."""
    if not key_values:
        return {}
    sql = "select id, key_value from potential_keys where key_value = any($1::text[])"
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(sql, key_values)
    return {row["key_value"]: row["id"] for row in rows}


async def scrape_github_keys(
    limit: int = 100,
    *,
    validate: bool = False,
    store: bool = False,
    start_query_index: Optional[int] = None,
    existing_keys: Optional[set[str]] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> list[ScrapedKey]:
    """Scrape GitHub Code Search for Gemini keys and return new ScrapedKey rows.

    Drives the rotating-token pool through the per-query loop with
    alternating sort, dedupes globally via ``seen_keys``, and stops as
    soon as ``len(results) >= limit``. When ``store`` is true the new
    rows are batch-inserted into ``potential_keys`` after the scrape;
    when ``validate`` is true each scraped key is validated inline (lazy
    import of Task 006).
    """
    db_pool = await get_supabase_pool()
    token_pool = GitHubTokenPool(db_pool)
    await token_pool.refresh_tokens()
    now = datetime.now(tz=timezone.utc)
    all_queries = build_all_queries(now)
    total_queries = len(all_queries)
    if total_queries == 0:
        logger.error("no scraper queries available; aborting")
        return []
    start_idx = (
        start_query_index
        if start_query_index is not None
        else random.randrange(total_queries)
    )
    rotated = all_queries[start_idx:] + all_queries[:start_idx]
    seen_keys: set[str] = set(existing_keys) if existing_keys else set()
    results: list[ScrapedKey] = []
    progress = ScrapeProgress(
        total=total_queries,
        current_source="github-code",
    )
    logger.info(
        "scrape start limit=%d queries=%d start_index=%d existing=%d",
        limit,
        total_queries,
        start_idx,
        len(seen_keys),
    )
    processed = 0
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for queue_index, query in enumerate(rotated):
            if len(results) >= limit:
                break
            progress.processed = queue_index + 1
            progress.current_source = f"github-code: {query[:30]}"
            emit_progress(progress, on_progress)
            logger.info(
                "scrape query %d/%d %r",
                queue_index + 1,
                total_queries,
                query[:LOG_PREVIEW_CHARS],
            )
            keep_going = await scrape_one_query(
                client=client,
                token_pool=token_pool,
                query=query,
                seen_keys=seen_keys,
                progress=progress,
                on_progress=on_progress,
                results=results,
                limit=limit,
            )
            processed = queue_index + 1
            if not keep_going:
                break
            await asyncio.sleep(INTER_QUERY_SLEEP)
    elapsed = (datetime.now(tz=timezone.utc) - progress.start_time).total_seconds()
    logger.info(
        "scrape end found=%d duplicates=%d processed=%d elapsed_s=%.1f",
        progress.found,
        progress.duplicates,
        processed,
        elapsed,
    )
    inserted_ids: dict[str, UUID] = {}
    if store and results:
        try:
            inserted_count = await insert_potential_keys_batch(db_pool, results)
            logger.info(
                "scrape stored new=%d total_attempted=%d",
                inserted_count,
                len(results),
            )
            inserted_ids = await _lookup_potential_ids(
                db_pool, [r.key for r in results]
            )
        except Exception as exc:  # noqa: BLE001 -- never lose results to a DB blip
            logger.error("scrape store failed: %s", exc)
    if validate and results:
        await _maybe_validate_inline(
            db_pool, results, progress, on_progress, inserted_ids
        )
    await _persist_query_index(db_pool, start_idx, processed, total_queries)
    return results


async def scrape_all_sources(
    limit: int = 200,
    *,
    validate: bool = False,
    store: bool = False,
    on_progress: Optional[ProgressCallback] = None,
) -> list[ScrapedKey]:
    """Scrape every supported source. Currently a thin wrapper over GitHub.

    Kept as a separate seam so adding a future source (e.g. GitHub Gists,
    GitLab) only touches this function rather than the orchestrator.
    """
    logger.info("scrape_all_sources start limit=%d", limit)
    keys = await scrape_github_keys(
        limit=limit,
        validate=validate,
        store=store,
        on_progress=on_progress,
    )
    logger.info(
        "scrape_all_sources end total=%d (github only)",
        len(keys),
    )
    return keys
