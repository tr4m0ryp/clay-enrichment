"""GitLab.com Code Search adapter.

GitLab is materially less-scanned by Google's Secret Scanner partner
program than GitHub: leaked Gemini keys committed to public GitLab
projects tend to survive longer than their GitHub counterparts.

Free-tier GitLab.com restriction: GLOBAL blob search
(``/api/v4/search?scope=blobs``) is Premium-only since 2024 and
returns ``403 Forbidden - Global Search is disabled for this scope``
on a free PAT. PROJECT-scoped blob search
(``/api/v4/projects/:id/search?scope=blobs``) is available to every
user with read access. We therefore work in two phases:

  1. Discover Gemini-related public projects via
     ``GET /api/v4/projects?search=<keyword>``. The keyword set targets
     projects likely to use the Gemini SDK (project name / description
     match).
  2. For each discovered project, run blob search inside that project
     with our standard key-pattern queries.

Rate-limit-friendly: GitLab.com allows ~600 req/min on search
endpoints with an authenticated PAT, vs GitHub's 30 search/min cap
per account. Per cycle we discover ~200 projects and do ~3 blob
searches each = ~600 calls = ~1 minute of throughput.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from src.api_keys.scraper._helpers import ProgressCallback, emit_progress
from src.api_keys.types import ScrapeMetadata, ScrapedKey, ScrapeProgress
from src.api_keys.utils import extract_keys_from_text, looks_like_gemini_context
from src.utils.logger import get_logger


logger = get_logger(__name__)


GITLAB_API_BASE = "https://gitlab.com/api/v4"
PER_PAGE: int = 100
DISCOVERY_PAGES_PER_KEYWORD: int = 3
BLOB_PAGES_PER_PROJECT: int = 2
INTER_CALL_SLEEP: float = 0.05
RATE_LIMIT_RETRY_SLEEP: float = 5.0

# Project-discovery keywords. Projects whose name/description matches
# any of these are very likely to use Gemini and therefore have a
# chance of containing a leaked AIzaSy with Gemini context.
PROJECT_DISCOVERY_KEYWORDS: tuple[str, ...] = (
    "gemini",
    "generative-ai",
    "generativeai",
    "google-genai",
    "googlegenai",
    "google-ai",
    "genai",
    "gemini-api",
)

# Per-project blob-search queries. Hits within a Gemini-related project
# pointing at any of these strings have very high yield.
BLOB_QUERIES: tuple[str, ...] = (
    "AIzaSy",
    "GEMINI_API_KEY",
    "GoogleGenerativeAI",
)


def _build_headers(token: str) -> dict[str, str]:
    return {
        "PRIVATE-TOKEN": token,
        "User-Agent": "clay-enrichment-keyscraper",
        "Accept": "application/json",
    }


def _build_metadata(blob: dict[str, Any], project_path: Optional[str]) -> ScrapeMetadata:
    return ScrapeMetadata(
        filename=blob.get("path") or blob.get("filename"),
        repository=project_path or str(blob.get("project_id", "?")),
        language=None,
        last_modified=None,
    )


async def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


async def _discover_projects(
    client: httpx.AsyncClient, token: str
) -> list[dict[str, Any]]:
    """Find public projects whose name/description matches one of the
    Gemini-related keywords. Deduplicates by project id."""
    seen_ids: set[int] = set()
    projects: list[dict[str, Any]] = []
    headers = _build_headers(token)
    for kw in PROJECT_DISCOVERY_KEYWORDS:
        for page in range(1, DISCOVERY_PAGES_PER_KEYWORD + 1):
            try:
                r = await client.get(
                    f"{GITLAB_API_BASE}/projects",
                    headers=headers,
                    params={
                        "search": kw,
                        "visibility": "public",
                        "per_page": PER_PAGE,
                        "page": page,
                        "order_by": "last_activity_at",
                        "simple": "true",
                    },
                    timeout=20.0,
                )
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                logger.warning("gitlab project discovery error kw=%s: %s", kw, exc)
                break
            if r.status_code == 429:
                await asyncio.sleep(RATE_LIMIT_RETRY_SLEEP)
                continue
            if not r.is_success:
                logger.warning(
                    "gitlab project discovery non-2xx kw=%s status=%d: %s",
                    kw, r.status_code, r.text[:120],
                )
                break
            data = await _safe_json(r)
            if not isinstance(data, list) or not data:
                break
            for proj in data:
                pid = proj.get("id")
                if isinstance(pid, int) and pid not in seen_ids:
                    seen_ids.add(pid)
                    projects.append(proj)
            if INTER_CALL_SLEEP > 0:
                await asyncio.sleep(INTER_CALL_SLEEP)
    logger.info("gitlab discovered %d unique projects", len(projects))
    return projects


async def _project_blob_search(
    client: httpx.AsyncClient, token: str, project_id: int, query: str
) -> list[dict[str, Any]]:
    """Search blobs inside a single project. Returns the union of up to
    BLOB_PAGES_PER_PROJECT pages of results (deduped by `path` within the
    project)."""
    seen_paths: set[str] = set()
    results: list[dict[str, Any]] = []
    headers = _build_headers(token)
    for page in range(1, BLOB_PAGES_PER_PROJECT + 1):
        try:
            r = await client.get(
                f"{GITLAB_API_BASE}/projects/{project_id}/search",
                headers=headers,
                params={
                    "scope": "blobs",
                    "search": query,
                    "per_page": PER_PAGE,
                    "page": page,
                },
                timeout=20.0,
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning(
                "gitlab blob search error pid=%d q=%r: %s",
                project_id, query[:40], exc,
            )
            break
        if r.status_code == 429:
            await asyncio.sleep(RATE_LIMIT_RETRY_SLEEP)
            continue
        if r.status_code in (403, 404):
            # 403: project disabled features; 404: archived/private.
            break
        if not r.is_success:
            break
        data = await _safe_json(r)
        if not isinstance(data, list) or not data:
            break
        for blob in data:
            path = blob.get("path")
            if path in seen_paths:
                continue
            seen_paths.add(path or "?")
            results.append(blob)
        if INTER_CALL_SLEEP > 0:
            await asyncio.sleep(INTER_CALL_SLEEP)
    return results


async def scrape_gitlab_keys(
    queries: list[str],  # accepted for signature parity with the github producer; ignored
    *,
    seen_keys: set[str],
    progress: ScrapeProgress,
    on_progress: Optional[ProgressCallback],
    results: list[ScrapedKey],
    limit: int,
    out_queue: Optional[asyncio.Queue] = None,
    token: Optional[str] = None,
) -> list[ScrapedKey]:
    """Two-phase GitLab scrape: discover projects then search their blobs.

    Signature matches the GitHub producer so the orchestrator's
    consumer pool fans-in candidates from both sources via the same
    shared ``out_queue``.
    """
    pat = token or os.environ.get("GITLAB_PAT")
    if not pat:
        logger.info("GITLAB_PAT not set; skipping GitLab source")
        return results
    del queries  # GitLab uses its own keyword list, not GitHub's query bank

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        projects = await _discover_projects(client, pat)
        logger.info(
            "gitlab scrape: %d projects, %d blob queries each",
            len(projects), len(BLOB_QUERIES),
        )
        for proj in projects:
            if limit > 0 and len(results) >= limit:
                break
            project_id = proj.get("id")
            project_path = proj.get("path_with_namespace")
            if not isinstance(project_id, int):
                continue
            for query in BLOB_QUERIES:
                if limit > 0 and len(results) >= limit:
                    break
                blobs = await _project_blob_search(client, pat, project_id, query)
                for blob in blobs:
                    if limit > 0 and len(results) >= limit:
                        break
                    snippet = blob.get("data") or ""
                    if not snippet:
                        continue
                    # Same context filter as the GitHub path -- biases
                    # toward files that demonstrably use Gemini.
                    if not looks_like_gemini_context(snippet):
                        continue
                    found = extract_keys_from_text(snippet)
                    path = blob.get("path") or "?"
                    src_url = (
                        f"https://gitlab.com/{project_path}/-/blob/main/{path}"
                        if project_path else f"gitlab://{project_id}/{path}"
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
                            metadata=_build_metadata(blob, project_path),
                            # Re-uses the "github" enum literal because
                            # the type system enforces it; provenance is
                            # tracked via the gitlab.com URL prefix.
                            source="github",
                        )
                        results.append(scraped)
                        if out_queue is not None:
                            await out_queue.put(scraped)
                        emit_progress(progress, on_progress)

    return results
