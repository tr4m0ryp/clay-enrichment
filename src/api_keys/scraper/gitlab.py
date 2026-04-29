"""GitLab.com Code Search adapter.

GitLab is materially less-scanned by Google's Secret Scanner partner program
than GitHub: the Scanner has a direct revocation pipeline with GitHub but
not with GitLab.com (GitLab's own secret detection runs as part of CI/CD,
not on every push). Leaked Gemini keys committed to public GitLab projects
therefore tend to survive much longer than their GitHub counterparts.

This module is the producer for a separate scrape entry point. It's
deliberately structured to mirror the GitHub scraper's contract: same
seen_keys / progress / out_queue plumbing so a single set of consumer
workers in the orchestrator can validate keys from either source.

GitLab API quirks worth knowing:
- /search?scope=blobs returns blob references with a ``data`` field
  containing the snippet around the search match. We extract keys from
  that snippet directly -- no second-step raw-file fetch is required.
- Authenticated rate limit is ~600 req/min per token (much friendlier
  than GitHub's 30/min search cap). Unauthenticated returns 401, so a
  PAT is mandatory; supplied via the GITLAB_PAT env var.
- per_page max is 100; pagination via ?page=N. GitLab caps total search
  results at 10,000 across all pages.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from src.api_keys.scraper._helpers import (
    ProgressCallback,
    emit_progress,
)
from src.api_keys.types import ScrapeMetadata, ScrapedKey, ScrapeProgress
from src.api_keys.utils import extract_keys_from_text
from src.utils.logger import get_logger


logger = get_logger(__name__)


GITLAB_API_BASE = "https://gitlab.com/api/v4"
GITLAB_SEARCH_URL = f"{GITLAB_API_BASE}/search"
PER_PAGE: int = 100
MAX_PAGES_PER_QUERY: int = 10
INTER_PAGE_SLEEP: float = 0.1
INTER_QUERY_SLEEP: float = 0.5
RATE_LIMIT_RETRY_SLEEP: float = 5.0


def _build_headers(token: str) -> dict[str, str]:
    return {
        "PRIVATE-TOKEN": token,
        "User-Agent": "clay-enrichment-keyscraper",
        "Accept": "application/json",
    }


def _build_metadata(blob: dict[str, Any]) -> ScrapeMetadata:
    """Pull metadata fields from a GitLab blob search hit."""
    project_id = blob.get("project_id")
    return ScrapeMetadata(
        filename=blob.get("path") or blob.get("filename"),
        repository=str(project_id) if project_id is not None else None,
        language=None,  # GitLab search doesn't return language inline
        last_modified=None,
    )


async def _fetch_search_page(
    *,
    client: httpx.AsyncClient,
    token: str,
    query: str,
    page: int,
) -> Optional[httpx.Response]:
    """One GitLab /search?scope=blobs request; returns the response or None."""
    params = {
        "scope": "blobs",
        "search": query,
        "per_page": PER_PAGE,
        "page": page,
    }
    return await client.get(
        GITLAB_SEARCH_URL,
        headers=_build_headers(token),
        params=params,
        timeout=20.0,
    )


async def scrape_gitlab_keys(
    queries: list[str],
    *,
    seen_keys: set[str],
    progress: ScrapeProgress,
    on_progress: Optional[ProgressCallback],
    results: list[ScrapedKey],
    limit: int,
    out_queue: Optional[asyncio.Queue] = None,
    token: Optional[str] = None,
) -> list[ScrapedKey]:
    """Run every query against GitLab; return the accumulated ScrapedKey list.

    ``token`` defaults to ``os.environ['GITLAB_PAT']``. If neither the env
    var nor the parameter is set, this function logs and returns the
    ``results`` list unchanged so the caller can chain it after the
    GitHub scrape without aborting.

    The signature deliberately matches the GitHub orchestrator's
    contract so the same consumer fan-out (insert/validate/upsert) in
    orchestrator.py works for both sources.
    """
    pat = token or os.environ.get("GITLAB_PAT")
    if not pat:
        logger.info("GITLAB_PAT not set; skipping GitLab source")
        return results

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for query in queries:
            if limit > 0 and len(results) >= limit:
                break
            page = 1
            while page <= MAX_PAGES_PER_QUERY and (limit <= 0 or len(results) < limit):
                response = await _fetch_search_page(
                    client=client, token=pat, query=query, page=page,
                )
                if response is None:
                    break
                if response.status_code == 429:
                    logger.warning(
                        "gitlab 429 query=%r retry after %ss",
                        query[:80], RATE_LIMIT_RETRY_SLEEP,
                    )
                    await asyncio.sleep(RATE_LIMIT_RETRY_SLEEP)
                    continue
                if response.status_code == 401:
                    logger.error("gitlab 401 (bad PAT?), aborting GitLab scrape")
                    return results
                if not response.is_success:
                    logger.warning(
                        "gitlab non-2xx status=%d query=%r body=%r",
                        response.status_code, query[:80],
                        response.text[:120],
                    )
                    break
                try:
                    blobs: list[dict[str, Any]] = response.json()
                except ValueError:
                    logger.error("gitlab bad json query=%r", query[:80])
                    break
                if not blobs:
                    break
                for blob in blobs:
                    if limit > 0 and len(results) >= limit:
                        break
                    snippet = blob.get("data") or ""
                    if not snippet:
                        continue
                    found = extract_keys_from_text(snippet)
                    project_id = blob.get("project_id")
                    path = blob.get("path") or "?"
                    src_url = (
                        f"https://gitlab.com/{project_id}/-/blob/main/{path}"
                        if project_id is not None else "gitlab://unknown"
                    )
                    for candidate in found:
                        if limit > 0 and len(results) >= limit:
                            break
                        if candidate in seen_keys:
                            progress.duplicates += 1
                            continue
                        seen_keys.add(candidate)
                        progress.found += 1
                        scraped = ScrapedKey(
                            key=candidate,
                            source_url=src_url,
                            found_at=datetime.now(tz=timezone.utc),
                            metadata=_build_metadata(blob),
                            # Re-uses the "github" source enum literal
                            # because the type system enforces it; the
                            # actual provenance is tracked via the
                            # gitlab.com URL prefix in source_url.
                            source="github",
                        )
                        results.append(scraped)
                        if out_queue is not None:
                            await out_queue.put(scraped)
                        emit_progress(progress, on_progress)
                if INTER_PAGE_SLEEP > 0:
                    await asyncio.sleep(INTER_PAGE_SLEEP)
                page += 1
            if INTER_QUERY_SLEEP > 0:
                await asyncio.sleep(INTER_QUERY_SLEEP)

    return results
