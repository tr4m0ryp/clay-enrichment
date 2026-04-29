"""Scrape orchestration with producer/consumer fan-out.

Producer: walks every static + dynamic GitHub Code Search query, dedupes
candidates via in-memory ``seen_keys``, and pushes each newly-found
ScrapedKey onto an ``asyncio.Queue``.

Consumers: ``validation_concurrency`` workers pull from the queue and
do ``insert_potential_key`` (stream) + ``validate_gemini_key`` +
``upsert_validated_key`` in parallel with the producer's ongoing scrape.
The total cycle time compresses from prior ``scrape_time + validate_time``
to ``max(scrape_time, validate_time)``.

Stream-insert means a process crash mid-scrape no longer loses every
candidate -- each row hits Postgres as soon as it's harvested.

``limit=0`` runs every query to exhaustion (no early stop). The cron
entrypoint defaults to that.
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
    insert_potential_key,
    update_system_status,
    upsert_validated_key,
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

# Sentinel pushed once per consumer to signal "no more keys are coming".
_DONE = object()

# Each consumer holds at most 2 connections (insert + upsert) plus its
# own httpx client; size accordingly against the asyncpg pool max_size
# in supabase_client.py.
_DEFAULT_VALIDATION_CONCURRENCY = 10

# Bounded queue so a stalled consumer doesn't let the producer balloon
# memory with thousands of buffered candidates.
_QUEUE_MAXSIZE = 200

# Sentinel for "unlimited" passed into scrape_one_query (which expects an
# int comparison). 1e9 is well above any plausible single-run yield.
_UNLIMITED_INT = 10**9


async def _persist_query_index(
    db_pool: asyncpg.Pool, start_index: int, processed: int, total: int
) -> None:
    """Persist the next-run starting index to ``system_status`` for ``scraper``."""
    if total <= 0:
        return
    next_index = (start_index + processed) % total
    try:
        await update_system_status(db_pool, "scraper", last_query_index=next_index)
    except Exception as exc:  # noqa: BLE001 -- bookkeeping must never abort
        logger.error("failed to persist last_query_index: %s", exc)


async def _consumer_worker(
    *,
    db_pool: asyncpg.Pool,
    queue: "asyncio.Queue[object]",
    progress: ScrapeProgress,
    on_progress: Optional[ProgressCallback],
    validate: bool,
    store: bool,
    http_timeout: float,
) -> None:
    """Pull ScrapedKey items from the queue; insert + validate + upsert.

    Each consumer owns its own httpx.AsyncClient so the validator can
    reuse a TCP connection across many keys without contention. asyncpg
    connections are acquired per-query from the shared pool.
    """
    # Lazy import: validator pulls heavy deps and the consumer is only
    # spawned when validate=True or store=True.
    from src.api_keys.validator import validate_gemini_key

    async with httpx.AsyncClient(timeout=http_timeout) as client:
        while True:
            item = await queue.get()
            try:
                if item is _DONE:
                    return
                scraped: ScrapedKey = item  # type: ignore[assignment]
                potential_id: Optional[UUID] = None
                if store:
                    try:
                        potential_id = await insert_potential_key(db_pool, scraped)
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "stream-insert failed key=%s err=%s",
                            scraped.key[:12], exc,
                        )
                # Skip validation for dups (insert_potential_key returns
                # None on conflict). The pending validate cron picks up
                # any orphan rows from prior partial runs.
                if validate and potential_id is not None:
                    try:
                        result = await validate_gemini_key(scraped.key, client=client)
                        await upsert_validated_key(db_pool, potential_id, result)
                        progress.validated += 1
                    except Exception as exc:  # noqa: BLE001
                        progress.validation_errors += 1
                        logger.error(
                            "validate failed key=%s err=%s",
                            scraped.key[:12], exc,
                        )
                emit_progress(progress, on_progress)
            finally:
                queue.task_done()


async def scrape_github_keys(
    limit: int = 0,
    *,
    validate: bool = False,
    store: bool = False,
    start_query_index: Optional[int] = None,
    existing_keys: Optional[set[str]] = None,
    on_progress: Optional[ProgressCallback] = None,
    validation_concurrency: int = _DEFAULT_VALIDATION_CONCURRENCY,
) -> list[ScrapedKey]:
    """Scrape GitHub Code Search; concurrently stream-insert + validate.

    ``limit=0`` (the default for cron usage) runs every static + dynamic
    query in the bank. A positive ``limit`` stops as soon as that many
    unique candidates have been emitted to the queue.
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
        start_query_index if start_query_index is not None
        else random.randrange(total_queries)
    )
    rotated = all_queries[start_idx:] + all_queries[:start_idx]
    seen_keys: set[str] = set(existing_keys) if existing_keys else set()
    results: list[ScrapedKey] = []
    progress = ScrapeProgress(total=total_queries, current_source="github-code")

    queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)

    do_per_key_work = store or validate
    consumer_count = validation_concurrency if do_per_key_work else 0
    consumer_tasks: list[asyncio.Task] = []
    if consumer_count:
        consumer_tasks = [
            asyncio.create_task(
                _consumer_worker(
                    db_pool=db_pool,
                    queue=queue,
                    progress=progress,
                    on_progress=on_progress,
                    validate=validate,
                    store=store,
                    http_timeout=30.0,
                )
            )
            for _ in range(consumer_count)
        ]

    effective_limit = limit if limit > 0 else _UNLIMITED_INT
    logger.info(
        "scrape start limit=%s queries=%d start_index=%d existing=%d consumers=%d",
        ("unlimited" if limit <= 0 else limit),
        total_queries, start_idx, len(seen_keys), consumer_count,
    )
    processed = 0
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for queue_index, query in enumerate(rotated):
                if limit > 0 and len(results) >= limit:
                    break
                progress.processed = queue_index + 1
                progress.current_source = f"github-code: {query[:30]}"
                emit_progress(progress, on_progress)
                logger.info(
                    "scrape query %d/%d %r",
                    queue_index + 1, total_queries, query[:LOG_PREVIEW_CHARS],
                )
                keep_going = await scrape_one_query(
                    client=client,
                    token_pool=token_pool,
                    query=query,
                    seen_keys=seen_keys,
                    progress=progress,
                    on_progress=on_progress,
                    results=results,
                    limit=effective_limit,
                    out_queue=queue if do_per_key_work else None,
                )
                processed = queue_index + 1
                if not keep_going:
                    break
                if INTER_QUERY_SLEEP > 0:
                    await asyncio.sleep(INTER_QUERY_SLEEP)
    finally:
        # Tell every consumer to drain + exit; then join the workers.
        for _ in range(consumer_count):
            await queue.put(_DONE)
        if consumer_tasks:
            await asyncio.gather(*consumer_tasks, return_exceptions=True)

    elapsed = (datetime.now(tz=timezone.utc) - progress.start_time).total_seconds()
    logger.info(
        "scrape end found=%d duplicates=%d processed_queries=%d "
        "validated=%d errors=%d elapsed_s=%.1f",
        progress.found, progress.duplicates, processed,
        progress.validated, progress.validation_errors, elapsed,
    )
    await _persist_query_index(db_pool, start_idx, processed, total_queries)
    return results


async def scrape_all_sources(
    limit: int = 0,
    *,
    validate: bool = False,
    store: bool = False,
    on_progress: Optional[ProgressCallback] = None,
) -> list[ScrapedKey]:
    """Scrape every supported source. Currently a thin wrapper over GitHub.

    Kept as a separate seam so adding a future source (gists, GitLab) only
    touches this function rather than the orchestrator's producer/consumer
    plumbing.
    """
    logger.info("scrape_all_sources start limit=%s", "unlimited" if limit <= 0 else limit)
    keys = await scrape_github_keys(
        limit=limit, validate=validate, store=store, on_progress=on_progress,
    )
    logger.info("scrape_all_sources end total=%d (github only)", len(keys))
    return keys
