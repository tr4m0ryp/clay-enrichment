"""Supabase asyncpg pool factory and supabase-py Auth-admin client.

Per D3 in notes/gemini-scraper-supabase-db-refactor.md the Python data layer
uses asyncpg directly against Supabase's direct Postgres endpoint (port 5432
or the eu-west-1 SESSION pooler), preserving prepared statements. This module
owns the singleton pool; src/db/connection.py re-exports it for backward
compatibility with the existing src/db/*.py modules.

The supabase-py client returned by get_supabase_client is reserved for Auth
admin and Storage calls; data queries always go through the asyncpg pool.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

import asyncpg
from supabase import Client, create_client


_pool: Optional[asyncpg.Pool] = None


async def get_supabase_pool() -> asyncpg.Pool:
    """Return the shared asyncpg pool to Supabase, creating it on first call.

    Reads the connection URL from the SUPABASE_DB_URL environment variable
    and surfaces a clear KeyError if the variable is missing. Pool size is
    bounded to min=2, max=25 connections; the upper bound exists to support
    the producer/consumer scrape pipeline where ~10 validator workers each
    can hold 2 connections (insert_potential_key + upsert_validated_key).
    """
    global _pool
    if _pool is None:
        url = os.environ["SUPABASE_DB_URL"]
        _pool = await asyncpg.create_pool(url, min_size=2, max_size=25)
    return _pool


async def close_supabase_pool() -> None:
    """Close the shared asyncpg pool if it has been created.

    Safe to call multiple times or before the pool is initialised.
    """
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return a cached service-role supabase-py client for Auth admin / Storage.

    NOT for data queries -- those go through get_supabase_pool. Reads
    SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from the environment.
    """
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)
