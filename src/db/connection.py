"""Backward-compatible re-export of the Supabase asyncpg pool.

The pool now lives in src.api_keys.supabase_client so the api_keys subsystem
and the existing src/db/*.py modules share a single connection pool against
Supabase (D3 in notes/gemini-scraper-supabase-db-refactor.md). Existing
callers continue to do `from src.db.connection import get_pool` unchanged.
"""

from src.api_keys.supabase_client import (
    close_supabase_pool as close_pool,
    get_supabase_pool as get_pool,
)

__all__ = ["get_pool", "close_pool"]
