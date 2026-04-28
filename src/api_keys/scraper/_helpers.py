"""Pure helpers for the scraper orchestrator.

Header construction, header parsing, and metadata extraction live here so
the orchestrator stays focused on the per-query loop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from src.api_keys.types import ScrapeMetadata, ScrapeProgress
from src.utils.logger import get_logger


logger = get_logger(__name__)


_USER_AGENT: str = "clay-enrichment-keyscraper"
_GITHUB_API_VERSION: str = "2022-11-28"
_GITHUB_ACCEPT: str = "application/vnd.github+json"


ProgressCallback = Callable[[ScrapeProgress], None]


def build_headers(token: Optional[str]) -> dict[str, str]:
    """Build the GitHub API request headers, including bearer auth if present."""
    headers: dict[str, str] = {
        "Accept": _GITHUB_ACCEPT,
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": _GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_reset_at(value: Optional[str]) -> Optional[datetime]:
    """Convert a unix-seconds string from x-ratelimit-reset to a UTC datetime."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def parse_remaining(value: Optional[str]) -> Optional[int]:
    """Parse the x-ratelimit-remaining header to an int (None on failure)."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def build_metadata(item: dict[str, Any]) -> ScrapeMetadata:
    """Pull the FrogBytes scrape metadata fields from one search result item."""
    repo = item.get("repository") or {}
    return ScrapeMetadata(
        filename=item.get("name"),
        repository=repo.get("full_name"),
        language=item.get("language"),
        last_modified=repo.get("updated_at"),
    )


def emit_progress(
    progress: ScrapeProgress, callback: Optional[ProgressCallback]
) -> None:
    """Invoke the progress callback if one was supplied; swallow exceptions."""
    if callback is None:
        return
    try:
        callback(progress)
    except Exception as exc:  # noqa: BLE001 -- callback contract is best-effort
        logger.warning("progress callback raised: %s", exc)
