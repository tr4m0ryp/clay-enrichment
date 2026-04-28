"""Raw GitHub file fetcher.

Translates ``github.com/<owner>/<repo>/blob/<sha>/<path>`` URLs into
``raw.githubusercontent.com/<owner>/<repo>/<sha>/<path>`` and downloads
the file body using a shared httpx client. Returns ``None`` for non-2xx
responses, transient network errors, or files larger than the configured
size cap so the caller can keep iterating without aborting the scrape.
"""

from __future__ import annotations

from typing import Optional

import httpx

from src.utils.logger import get_logger


logger = get_logger(__name__)


# Files larger than this are skipped to avoid wasting bandwidth and CPU
# on huge build artefacts. Mirrors the FrogBytes 500KB ceiling.
MAX_FILE_BYTES: int = 500_000


def to_raw_url(html_url: str) -> str:
    """Convert a github.com blob URL into its raw.githubusercontent.com twin.

    Replaces the host and drops the ``/blob/`` path segment in one pass.
    Inputs that are already raw URLs return unchanged because the host
    swap and ``/blob/`` strip are both idempotent.
    """
    raw = html_url.replace("github.com", "raw.githubusercontent.com")
    raw = raw.replace("/blob/", "/")
    return raw


async def fetch_raw_file(
    client: httpx.AsyncClient, html_url: str
) -> Optional[str]:
    """GET the raw file body or ``None`` if it should be skipped.

    Skip reasons (each logged at warning):
        * ``html_url`` could not be translated (no github.com host)
        * non-2xx response from raw.githubusercontent.com
        * response body exceeds ``MAX_FILE_BYTES``
        * httpx raised a transport / timeout error

    The shared client supplies the timeout and follow_redirects policy so
    callers can configure them once at the top of the scrape.
    """
    raw_url = to_raw_url(html_url)
    try:
        response = await client.get(raw_url)
    except httpx.HTTPError as exc:
        logger.warning("raw fetch failed url=%s err=%s", raw_url, exc)
        return None

    if not response.is_success:
        logger.warning(
            "raw fetch non-2xx url=%s status=%d",
            raw_url,
            response.status_code,
        )
        return None

    content_length = len(response.content)
    if content_length > MAX_FILE_BYTES:
        logger.warning(
            "raw fetch skipped (too large) url=%s bytes=%d",
            raw_url,
            content_length,
        )
        return None

    try:
        return response.text
    except UnicodeDecodeError as exc:
        # Binary blobs sometimes survive the size guard; treat them as
        # unreadable rather than crashing the scrape.
        logger.warning("raw decode failed url=%s err=%s", raw_url, exc)
        return None
