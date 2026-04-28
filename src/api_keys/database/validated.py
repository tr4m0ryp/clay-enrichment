"""asyncpg primitives over the ``validated_keys`` table.

Owned by the validator (upsert), the manager (pick + capability toggles +
failure counter), and the dashboard (read-only listing).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional
from uuid import UUID

import asyncpg

from src.api_keys.types import KeyValidationResult, ValidationStatus

from src.api_keys.database._internal import (
    AUTO_DISABLE_STATUS,
    capabilities_to_dict,
    encode_json,
)


async def upsert_validated_key(
    pool: asyncpg.Pool, potential_key_id: UUID, result: KeyValidationResult
) -> UUID:
    """Insert or update the validated_keys row for ``potential_key_id``.

    The schema has no unique constraint on ``potential_key_id``, so we run
    SELECT-then-UPDATE-or-INSERT inside a transaction. Resets
    ``consecutive_failures`` to 0 on every fresh validation pass and stores
    capabilities as a jsonb dict keyed by model name.
    """
    capabilities = capabilities_to_dict(result)
    rate_limit = (
        asdict(result.rate_limit_info) if result.rate_limit_info is not None else None
    )
    select_sql = "select id from validated_keys where potential_key_id = $1 limit 1"
    update_sql = """
        update validated_keys
        set
          key_value                = $2,
          is_valid                 = $3,
          status                   = $4,
          capabilities             = $5::jsonb,
          total_models_accessible  = $6,
          total_models_tested      = $7,
          average_response_time_ms = $8,
          quota_remaining          = $9,
          rate_limit_info          = $10::jsonb,
          validated_at             = now(),
          consecutive_failures     = 0
        where id = $1
        returning id
    """
    insert_sql = """
        insert into validated_keys (
          potential_key_id, key_value, is_valid, status, capabilities,
          total_models_accessible, total_models_tested, average_response_time_ms,
          quota_remaining, rate_limit_info, validated_at, consecutive_failures
        )
        values ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10::jsonb, now(), 0)
        returning id
    """
    args_tail = (
        result.key,
        result.is_valid,
        result.status,
        encode_json(capabilities),
        result.total_models_accessible,
        result.total_models_tested,
        result.average_response_time_ms,
        result.quota_remaining,
        encode_json(rate_limit),
    )
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchval(select_sql, potential_key_id)
            if existing is not None:
                return await conn.fetchval(update_sql, existing, *args_tail)
            return await conn.fetchval(insert_sql, potential_key_id, *args_tail)


async def pick_validated_key(
    pool: asyncpg.Pool, model_name: str
) -> Optional[tuple[UUID, str]]:
    """Atomically pick a usable validated key for ``model_name`` or None.

    Uses FOR UPDATE SKIP LOCKED so concurrent pipeline workers never collide.
    Filters on ``capabilities -> $1 ->> 'is_accessible' = true``, which
    requires capabilities to be stored as a dict-by-model.
    """
    sql = """
        update validated_keys
        set last_used_at = now()
        where id = (
          select id from validated_keys
          where status = 'valid'
            and consecutive_failures < 3
            and (capabilities -> $1 ->> 'is_accessible')::bool = true
          order by last_used_at nulls first
          limit 1
          for update skip locked
        )
        returning id, key_value
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, model_name)
    if row is None:
        return None
    return row["id"], row["key_value"]


async def increment_consecutive_failures(
    pool: asyncpg.Pool, validated_key_id: UUID, threshold: int = 3
) -> int:
    """Atomic +1 on consecutive_failures; auto-disables at >= threshold."""
    sql = """
        update validated_keys
        set
          consecutive_failures = consecutive_failures + 1,
          status = case
            when consecutive_failures + 1 >= $2 then $3
            else status
          end
        where id = $1
        returning consecutive_failures
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, validated_key_id, threshold, AUTO_DISABLE_STATUS)


async def reset_consecutive_failures(
    pool: asyncpg.Pool, validated_key_id: UUID
) -> None:
    """Zero consecutive_failures for one validated_keys row."""
    sql = "update validated_keys set consecutive_failures = 0 where id = $1"
    async with pool.acquire() as conn:
        await conn.execute(sql, validated_key_id)


async def update_validated_capability(
    pool: asyncpg.Pool, validated_key_id: UUID, model_name: str, is_accessible: bool
) -> None:
    """Toggle ``capabilities -> <model_name> -> is_accessible`` in jsonb."""
    sql = """
        update validated_keys
        set capabilities = jsonb_set(
          coalesce(capabilities, '{}'::jsonb),
          array[$2, 'is_accessible'],
          to_jsonb($3::bool),
          true
        )
        where id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute(sql, validated_key_id, model_name, is_accessible)


async def mark_validated_key_status(
    pool: asyncpg.Pool, validated_key_id: UUID, status: ValidationStatus
) -> None:
    """Set the status column on a single validated_keys row."""
    sql = "update validated_keys set status = $2 where id = $1"
    async with pool.acquire() as conn:
        await conn.execute(sql, validated_key_id, status)


async def get_active_validated_keys(
    pool: asyncpg.Pool, limit: int = 1000
) -> list[asyncpg.Record]:
    """Return validated_keys rows with status='valid', oldest-used first."""
    sql = """
        select * from validated_keys
        where status = 'valid'
        order by last_used_at nulls first
        limit $1
    """
    async with pool.acquire() as conn:
        return await conn.fetch(sql, limit)
