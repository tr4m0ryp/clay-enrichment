"""Per-query / per-page scraping primitives.

Builds search URLs, executes one search request, handles 403/429 token
rotation, records rate-limit headers on success, and walks the result
items through ``fetch_raw_file`` plus ``extract_keys_from_text``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

from src.api_keys.github_token_pool import GitHubTokenPool
from src.api_keys.scraper._helpers import (
    ProgressCallback,
    build_headers,
    build_metadata,
    emit_progress,
    parse_remaining,
    parse_reset_at,
)
from src.api_keys.scraper.fetcher import fetch_raw_file
from src.api_keys.types import ScrapedKey, ScrapeProgress
from src.api_keys.utils import extract_keys_from_text
from src.utils.logger import get_logger


logger = get_logger(__name__)


MAX_PAGES_PER_QUERY: int = 3
PER_PAGE: int = 100
INTER_FILE_SLEEP: float = 0.2
INTER_PAGE_SLEEP: float = 0.5
INTER_QUERY_SLEEP: float = 1.0
RATE_LIMIT_RETRY_SLEEP: float = 1.0
EMPTY_POOL_SLEEP: float = 60.0
PROACTIVE_ROTATE_THRESHOLD: int = 10
LOG_PREVIEW_CHARS: int = 200


_SEARCH_URL_TEMPLATE: str = (
    "https://api.github.com/search/code"
    "?q={query}&per_page={per_page}&page={page}&sort={sort}&order=desc"
)
_SORT_ORDER: tuple[str, str] = ("indexed", "updated")


async def fetch_search_page(
    *,
    client: httpx.AsyncClient,
    pool: GitHubTokenPool,
    query: str,
    page: int,
) -> Optional[httpx.Response]:
    """One GET against /search/code; returns the response or None to abort."""
    token = await pool.get_current_token()
    if token is None:
        await asyncio.sleep(EMPTY_POOL_SLEEP)
        await pool.refresh_tokens()
        token = await pool.get_current_token()
        if token is None:
            logger.error("scraper aborting: no github tokens available")
            return None
    sort = _SORT_ORDER[page % 2]
    url = _SEARCH_URL_TEMPLATE.format(
        query=quote_plus(query),
        per_page=PER_PAGE,
        page=page,
        sort=sort,
    )
    return await client.get(url, headers=build_headers(token))


async def handle_rate_limited(
    pool: GitHubTokenPool, response: httpx.Response
) -> bool:
    """Mark the current token rate-limited and rotate; return False if drained."""
    reset_at = parse_reset_at(response.headers.get("x-ratelimit-reset"))
    await pool.mark_current_rate_limited(reset_at)
    if pool.token_count() > 0:
        await pool.rotate_to_next()
        await asyncio.sleep(RATE_LIMIT_RETRY_SLEEP)
        return True
    await asyncio.sleep(EMPTY_POOL_SLEEP)
    await pool.refresh_tokens()
    return pool.token_count() > 0


async def record_success(
    pool: GitHubTokenPool, response: httpx.Response
) -> None:
    """Persist the rate-limit headers + proactively rotate when remaining is low."""
    remaining = parse_remaining(response.headers.get("x-ratelimit-remaining"))
    reset_at = parse_reset_at(response.headers.get("x-ratelimit-reset"))
    await pool.mark_success(remaining, reset_at)
    if (
        remaining is not None
        and remaining < PROACTIVE_ROTATE_THRESHOLD
        and pool.token_count() > 1
    ):
        logger.info(
            "rotating proactively: remaining=%d below threshold=%d",
            remaining,
            PROACTIVE_ROTATE_THRESHOLD,
        )
        await pool.rotate_to_next()


async def process_search_item(
    *,
    client: httpx.AsyncClient,
    item: dict[str, Any],
    seen_keys: set[str],
    progress: ScrapeProgress,
    on_progress: Optional[ProgressCallback],
    results: list[ScrapedKey],
    limit: int,
) -> None:
    """Fetch one matched file, extract keys, append unique ones to results."""
    html_url = item.get("html_url")
    if not html_url:
        return
    repo = item.get("repository") or {}
    logger.info(
        "scanning file repo=%s name=%s",
        repo.get("full_name"),
        item.get("name"),
    )
    body = await fetch_raw_file(client, html_url)
    if body is None:
        return
    found = extract_keys_from_text(body)
    for candidate in found:
        if len(results) >= limit:
            return
        if candidate in seen_keys:
            progress.duplicates += 1
            continue
        seen_keys.add(candidate)
        progress.found += 1
        results.append(
            ScrapedKey(
                key=candidate,
                source_url=html_url,
                found_at=datetime.now(tz=timezone.utc),
                metadata=build_metadata(item),
            )
        )
        emit_progress(progress, on_progress)


async def scrape_one_query(
    *,
    client: httpx.AsyncClient,
    token_pool: GitHubTokenPool,
    query: str,
    seen_keys: set[str],
    progress: ScrapeProgress,
    on_progress: Optional[ProgressCallback],
    results: list[ScrapedKey],
    limit: int,
) -> bool:
    """Run the per-query 3-page loop. Return False to abort the whole scrape."""
    page = 1
    while page <= MAX_PAGES_PER_QUERY and len(results) < limit:
        response = await fetch_search_page(
            client=client, pool=token_pool, query=query, page=page
        )
        if response is None:
            return False
        if response.status_code in (403, 429):
            if not await handle_rate_limited(token_pool, response):
                return False
            continue
        if not response.is_success:
            preview = response.text[:LOG_PREVIEW_CHARS]
            logger.error(
                "github search non-2xx status=%d query=%r body=%r",
                response.status_code,
                query[:LOG_PREVIEW_CHARS],
                preview,
            )
            break
        await record_success(token_pool, response)
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            logger.error("github search bad json query=%r err=%s", query, exc)
            break
        items = data.get("items") or []
        if not items:
            break
        for item in items:
            if len(results) >= limit:
                break
            await process_search_item(
                client=client,
                item=item,
                seen_keys=seen_keys,
                progress=progress,
                on_progress=on_progress,
                results=results,
                limit=limit,
            )
            await asyncio.sleep(INTER_FILE_SLEEP)
        await asyncio.sleep(INTER_PAGE_SLEEP)
        page += 1
    return True
