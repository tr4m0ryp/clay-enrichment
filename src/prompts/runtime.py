"""Prompt override resolver.

Each prompt module defines a ``_DEFAULT_X`` raw string and exposes its
final constant via ``resolve("<key>", _DEFAULT_X)``. ``resolve`` checks
the Postgres ``settings`` table (rows with key ``prompt:<key>``) the
first time it runs and caches the result for the lifetime of the
process. Pipeline restart re-reads the table -- save in the UI then
restart ``clay-pipeline`` to pick up new prompts.

Sync access is intentional: prompt constants are evaluated at module
import time, well before any asyncio loop exists. ``psycopg2`` keeps
this lightweight without dragging asyncio into the prompt layer.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_PREFIX = "prompt:"
_cache: Optional[dict[str, str]] = None


def _load_sync() -> dict[str, str]:
    """Read all prompt overrides from the settings table (sync)."""
    url = os.environ.get("SUPABASE_DB_URL", "")
    if not url:
        return {}

    try:
        import psycopg2
    except ImportError:
        logger.warning(
            "psycopg2 not installed, prompt overrides disabled "
            "(install psycopg2-binary to enable)."
        )
        return {}

    try:
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT key, value FROM settings WHERE key LIKE %s",
                    (f"{_PREFIX}%",),
                )
                rows = cur.fetchall()
        out: dict[str, str] = {}
        for key, value in rows:
            if not isinstance(value, str) or not value.strip():
                continue
            out[key[len(_PREFIX):]] = value
        if out:
            logger.info("Loaded %d prompt override(s) from DB", len(out))
        return out
    except Exception:
        logger.exception("Prompt override load failed; falling back to defaults")
        return {}


def resolve(key: str, default: str) -> str:
    """Return the override for ``key`` if one is set, else ``default``."""
    global _cache
    if _cache is None:
        _cache = _load_sync()
    return _cache.get(key, default)


def reload() -> None:
    """Drop the cache so the next ``resolve`` re-reads from DB."""
    global _cache
    _cache = None
