"""asyncpg primitive for the ``key_pool_logs`` table.

The dashboard renders recent activity from these rows. Logging is
non-fatal: any insert exception is swallowed and forwarded to the
process-level Python logger so that DB hiccups never abort a worker.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

import asyncpg

from src.api_keys.database._internal import encode_json
from src.utils.logger import get_logger


logger = get_logger(__name__)


async def append_log(
    pool: asyncpg.Pool,
    service: str,
    level: str,
    message: str,
    *,
    meta: Optional[dict] = None,
    execution_id: Optional[UUID] = None,
) -> None:
    """Insert one structured log row. Swallow exceptions on the DB path."""
    sql = """
        insert into key_pool_logs (service, level, message, meta, execution_id)
        values ($1, $2, $3, $4::jsonb, $5)
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                sql, service, level, message, encode_json(meta), execution_id
            )
    except Exception as exc:  # noqa: BLE001 -- logging path must never raise
        logger.warning(
            "append_log failed (service=%s, level=%s): %s", service, level, exc
        )
