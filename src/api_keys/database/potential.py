"""asyncpg primitives over the ``potential_keys`` table.

Owned by the scraper (writes) and the validator (reads pending rows and
flips status). All SQL is parameterised with ``$N`` placeholders.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional
from uuid import UUID

import asyncpg

from src.api_keys.types import ScrapedKey, ValidationStatus

from src.api_keys.database._internal import encode_json


async def insert_potential_key(
    pool: asyncpg.Pool, key: ScrapedKey
) -> Optional[UUID]:
    """Insert one scraped key. Returns the new id, or None if it was a duplicate."""
    sql = """
        insert into potential_keys (key_value, source, source_url, found_at, metadata)
        values ($1, $2, $3, $4, $5::jsonb)
        on conflict (key_value) do nothing
        returning id
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            sql,
            key.key,
            key.source,
            key.source_url,
            key.found_at,
            encode_json(asdict(key.metadata)),
        )


async def insert_potential_keys_batch(
    pool: asyncpg.Pool, keys: list[ScrapedKey]
) -> int:
    """Insert many scraped keys atomically; return the count of NEW rows.

    Uses ``xmax = 0`` to distinguish freshly inserted rows from rows that
    matched an existing ``key_value`` -- ``ON CONFLICT DO NOTHING`` leaves
    xmax non-zero on a conflict, so the boolean expression yields false.
    """
    if not keys:
        return 0
    sql = """
        insert into potential_keys (key_value, source, source_url, found_at, metadata)
        select
          unnest($1::text[]),
          unnest($2::text[]),
          unnest($3::text[]),
          unnest($4::timestamptz[]),
          unnest($5::jsonb[])
        on conflict (key_value) do nothing
        returning (xmax = 0) as inserted
    """
    values = [k.key for k in keys]
    sources = [k.source for k in keys]
    urls = [k.source_url for k in keys]
    found = [k.found_at for k in keys]
    metas = [encode_json(asdict(k.metadata)) for k in keys]
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, values, sources, urls, found, metas)
    return sum(1 for r in rows if r["inserted"])


async def get_existing_key_values(
    pool: asyncpg.Pool, candidates: list[str]
) -> set[str]:
    """Return the subset of ``candidates`` already present in potential_keys."""
    if not candidates:
        return set()
    sql = "select key_value from potential_keys where key_value = any($1::text[])"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, candidates)
    return {r["key_value"] for r in rows}


async def get_pending_potential_keys(
    pool: asyncpg.Pool, limit: int = 100
) -> list[tuple[UUID, str]]:
    """Return up to ``limit`` (id, key_value) pairs awaiting validation."""
    sql = """
        select id, key_value from potential_keys
        where validation_status = 'pending'
        order by found_at asc
        limit $1
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, limit)
    return [(r["id"], r["key_value"]) for r in rows]


async def update_potential_key_status(
    pool: asyncpg.Pool, potential_key_id: UUID, status: ValidationStatus
) -> None:
    """Set validation_status (and validated_at = now()) for one row."""
    sql = """
        update potential_keys
        set validation_status = $2, validated_at = now()
        where id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute(sql, potential_key_id, status)
