"""Hugging Face Spaces adapter.

Hugging Face Spaces hosts AI demo apps (Gradio / Streamlit / static).
A large share of public Spaces are tutorial/demo deployments that
hardcode a Gemini key into ``app.py``, ``.env``, ``config.py``, or
the README so visitors can click "Run" without configuring anything.
Google's Secret Scanner partner program does NOT cover huggingface.co,
so these keys typically persist for months instead of being auto-
revoked within minutes (the GitHub fate).

Two-phase scrape:

  1. Discover Spaces matching Gemini-related keywords via
     ``GET /api/spaces?search=<kw>&limit=100``. Pagination via
     ``?cursor=<token>`` (HF uses cursor-based pagination, not
     page numbers).
  2. For each discovered Space, list interesting files via the repo
     tree endpoint, then fetch raw bodies of files that are likely
     to contain a key (.env, .py, config*, README, etc.). Apply the
     same Gemini-context filter we use for GitHub/GitLab.

HF tokens unlock generous rate limits (~10 k req/hour). Without a
token the public endpoints still work but at ~100 req/min total --
fine for a few hundred Spaces per cycle.
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


HF_API_BASE = "https://huggingface.co/api"
HF_RAW_BASE = "https://huggingface.co"
PER_PAGE: int = 100
DISCOVERY_PAGES_PER_KEYWORD: int = 3
MAX_FILES_PER_SPACE: int = 12
INTER_CALL_SLEEP: float = 0.05
RATE_LIMIT_RETRY_SLEEP: float = 5.0
MAX_FILE_BYTES: int = 500_000

# Keywords that catch Gemini-themed Spaces. Spaces whose name /
# description / tags contain any of these are very likely to host a
# real Gemini key in their app code.
DISCOVERY_KEYWORDS: tuple[str, ...] = (
    "gemini",
    "generativeai",
    "google-genai",
    "googlegenai",
    "google-ai",
    "genai",
    "gemini-api",
    "google-generative-ai",
)

# File-path substrings (lowercased) that are worth raw-fetching when
# discovered in a Space's repo tree. We deliberately skip large model
# weights, audio/video assets, and node_modules.
INTERESTING_FILE_PATTERNS: tuple[str, ...] = (
    "app.py", "main.py", "run.py", "demo.py", "streamlit_app.py",
    ".env", ".env.local", ".env.example",
    "config.py", "config.json", "config.yaml", "config.yml",
    "settings.py", "settings.json", "secrets",
    "readme", ".md",
    ".js", ".ts", ".jsx", ".tsx",
    "package.json", "tsconfig.json",
    "requirements.txt", "pyproject.toml",
    ".env",
)
SKIP_DIR_SUBSTRINGS: tuple[str, ...] = (
    "node_modules/", ".git/", "__pycache__/", "dist/", "build/",
    "venv/", ".venv/",
)
SKIP_FILE_EXTENSIONS: tuple[str, ...] = (
    ".bin", ".pt", ".pth", ".onnx", ".safetensors",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".mp3", ".mp4", ".wav", ".ogg",
    ".zip", ".tar", ".gz", ".7z",
    ".lock",
)


def _build_headers(token: Optional[str]) -> dict[str, str]:
    headers: dict[str, str] = {
        "User-Agent": "clay-enrichment-keyscraper",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_interesting_path(path: str) -> bool:
    """Filter the repo tree down to files likely to hold a key."""
    if not path:
        return False
    lower = path.lower()
    if any(skip in lower for skip in SKIP_DIR_SUBSTRINGS):
        return False
    if any(lower.endswith(ext) for ext in SKIP_FILE_EXTENSIONS):
        return False
    return any(p in lower for p in INTERESTING_FILE_PATTERNS)


def _build_metadata(space_id: str, path: str) -> ScrapeMetadata:
    return ScrapeMetadata(
        filename=path,
        repository=space_id,
        language=None,
        last_modified=None,
    )


async def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


async def _discover_spaces(
    client: httpx.AsyncClient, token: Optional[str]
) -> list[dict[str, Any]]:
    """Search public Spaces by keyword. Deduplicates by space id."""
    seen: set[str] = set()
    spaces: list[dict[str, Any]] = []
    headers = _build_headers(token)
    for kw in DISCOVERY_KEYWORDS:
        for page in range(DISCOVERY_PAGES_PER_KEYWORD):
            try:
                r = await client.get(
                    f"{HF_API_BASE}/spaces",
                    headers=headers,
                    params={
                        "search": kw,
                        "limit": PER_PAGE,
                        "full": "true",
                        "skip": page * PER_PAGE,
                    },
                    timeout=20.0,
                )
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                logger.warning("hf discovery error kw=%s: %s", kw, exc)
                break
            if r.status_code == 429:
                await asyncio.sleep(RATE_LIMIT_RETRY_SLEEP)
                continue
            if not r.is_success:
                logger.warning(
                    "hf discovery non-2xx kw=%s status=%d body=%r",
                    kw, r.status_code, r.text[:120],
                )
                break
            data = await _safe_json(r)
            if not isinstance(data, list) or not data:
                break
            for space in data:
                space_id = space.get("id")
                if isinstance(space_id, str) and space_id not in seen:
                    seen.add(space_id)
                    spaces.append(space)
            if INTER_CALL_SLEEP > 0:
                await asyncio.sleep(INTER_CALL_SLEEP)
    logger.info("hf discovered %d unique spaces", len(spaces))
    return spaces


async def _list_space_files(
    client: httpx.AsyncClient, token: Optional[str], space_id: str
) -> list[str]:
    """Walk the Space's repo tree and return up to MAX_FILES_PER_SPACE
    paths that look key-bearing."""
    interesting: list[str] = []
    headers = _build_headers(token)
    try:
        r = await client.get(
            f"{HF_API_BASE}/spaces/{space_id}/tree/main",
            headers=headers,
            params={"recursive": "true"},
            timeout=20.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.debug("hf tree error %s: %s", space_id, exc)
        return interesting
    if r.status_code == 429:
        await asyncio.sleep(RATE_LIMIT_RETRY_SLEEP)
        return interesting
    if not r.is_success:
        return interesting
    data = await _safe_json(r)
    if not isinstance(data, list):
        return interesting
    for entry in data:
        if entry.get("type") != "file":
            continue
        path = entry.get("path") or ""
        size = entry.get("size") or 0
        if size > MAX_FILE_BYTES:
            continue
        if _is_interesting_path(path):
            interesting.append(path)
            if len(interesting) >= MAX_FILES_PER_SPACE:
                break
    return interesting


async def _fetch_raw(
    client: httpx.AsyncClient, token: Optional[str], space_id: str, path: str
) -> Optional[str]:
    """Fetch the raw bytes of one file from a Space."""
    headers = _build_headers(token)
    url = f"{HF_RAW_BASE}/spaces/{space_id}/raw/main/{path}"
    try:
        r = await client.get(url, headers=headers, timeout=20.0)
    except (httpx.TimeoutException, httpx.RequestError):
        return None
    if r.status_code != 200:
        return None
    if len(r.content) > MAX_FILE_BYTES:
        return None
    try:
        return r.text
    except UnicodeDecodeError:
        return None


async def scrape_huggingface_keys(
    queries: list[str],  # accepted for signature parity; ignored
    *,
    seen_keys: set[str],
    progress: ScrapeProgress,
    on_progress: Optional[ProgressCallback],
    results: list[ScrapedKey],
    limit: int,
    out_queue: Optional[asyncio.Queue] = None,
    token: Optional[str] = None,
) -> list[ScrapedKey]:
    """Two-phase HF scrape: discover Gemini Spaces then fetch interesting files.

    Signature mirrors the GitHub / GitLab producers so the consumer
    pool fans-in candidates from any source via the shared ``out_queue``.
    """
    auth = token or os.environ.get("HF_TOKEN")
    if not auth:
        logger.info("HF_TOKEN not set; HF scrape will use unauthenticated low-rate limits")
    del queries  # HF uses its own keyword set, not GitHub's query bank

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        spaces = await _discover_spaces(client, auth)
        logger.info(
            "hf scrape: %d spaces, up to %d files each",
            len(spaces), MAX_FILES_PER_SPACE,
        )
        for space in spaces:
            if limit > 0 and len(results) >= limit:
                break
            space_id = space.get("id")
            if not isinstance(space_id, str):
                continue
            paths = await _list_space_files(client, auth, space_id)
            for path in paths:
                if limit > 0 and len(results) >= limit:
                    break
                body = await _fetch_raw(client, auth, space_id, path)
                if not body:
                    continue
                if not looks_like_gemini_context(body):
                    continue
                found = extract_keys_from_text(body)
                src_url = f"{HF_RAW_BASE}/spaces/{space_id}/blob/main/{path}"
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
                        metadata=_build_metadata(space_id, path),
                        # Re-uses the "github" source enum literal because
                        # the type system enforces it; provenance tracked
                        # via the huggingface.co URL prefix.
                        source="github",
                    )
                    results.append(scraped)
                    if out_queue is not None:
                        await out_queue.put(scraped)
                    emit_progress(progress, on_progress)
                if INTER_CALL_SLEEP > 0:
                    await asyncio.sleep(INTER_CALL_SLEEP)

    return results
