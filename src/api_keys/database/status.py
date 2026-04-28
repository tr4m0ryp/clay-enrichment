"""asyncpg primitives over the ``system_status`` table.

The manager (Task 007) and the workers (Tasks 005/006) read+write a single
row keyed by ``service``. Updates are whitelist-driven so callers cannot
inject column names. The seed row for ``gemini_tier_manager`` is created by
the 005 migration; this module also performs an upsert on first contact for
any other ``service`` value so workers do not need to seed manually.
"""

from __future__ import annotations

from typing import Any, Optional

import asyncpg

from src.api_keys.database._internal import (
    ALLOWED_SERVICES,
    build_status_update,
)


async def get_system_status(
    pool: asyncpg.Pool, service: str
) -> Optional[asyncpg.Record]:
    """Return the system_status row for ``service`` or None."""
    if service not in ALLOWED_SERVICES:
        raise ValueError(f"unknown service: {service!r}")
    sql = "select * from system_status where service = $1"
    async with pool.acquire() as conn:
        return await conn.fetchrow(sql, service)


async def update_system_status(
    pool: asyncpg.Pool, service: str, **fields: Any
) -> None:
    """Whitelist-driven update of the system_status row keyed by ``service``.

    Unknown columns are silently ignored. Upserts the row so callers don't
    need to seed it manually -- a fresh insert defaults state='active' if
    not provided. ``state`` is NOT NULL in the schema, so the insert path
    always supplies a value.
    """
    if service not in ALLOWED_SERVICES:
        raise ValueError(f"unknown service: {service!r}")
    set_clause, values = build_status_update(fields)
    if not set_clause:
        return
    initial_state = fields.get("state", "active")
    sql = f"""
        insert into system_status (service, state)
        values ($1, ${len(values) + 2})
        on conflict (service) do update set {set_clause}
    """
    async with pool.acquire() as conn:
        await conn.execute(sql, service, *values, initial_state)
