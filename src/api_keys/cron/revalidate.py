"""Cron entrypoint: re-test validated_keys rows older than 24 hours.

Runs daily via systemd timer. Selects validated_keys whose last validation
was more than 24 hours ago and whose status is currently usable
(``valid``/``quota_reached``/``quota_exceeded``), re-runs the full validator
(``full=True`` so quota/rate-limit fields refresh too), and upserts the
new capabilities. Persists run state to the ``revalidator`` row in
system_status.

Run as: ``python -m src.api_keys.cron.revalidate``
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone

from src.api_keys.database import (
    append_log,
    update_system_status,
    upsert_validated_key,
)
from src.api_keys.supabase_client import close_supabase_pool, get_supabase_pool
from src.api_keys.validator import validate_gemini_key
from src.utils.logger import get_logger


logger = get_logger(__name__)
SERVICE = "revalidator"

_SELECT_STALE_KEYS_SQL = """
    select id, potential_key_id, key_value
    from validated_keys
    where status in ('valid','quota_reached','quota_exceeded')
      and (validated_at is null or validated_at < now() - interval '24 hours')
    limit 500
"""


async def _run(pool, execution_id: uuid.UUID) -> dict:
    """Re-test up to 500 stale validated_keys rows; return run stats."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SELECT_STALE_KEYS_SQL)
    revalidated = 0
    failed = 0
    for row in rows:
        try:
            result = await validate_gemini_key(row["key_value"], full=True)
            await upsert_validated_key(pool, row["potential_key_id"], result)
            revalidated += 1
        except Exception as exc:  # noqa: BLE001 -- isolate per-key failures
            failed += 1
            logger.exception("revalidate failed for %s: %s", row["id"], exc)
    return {
        "revalidated": revalidated,
        "failed": failed,
        "total": len(rows),
    }


async def main() -> int:
    """Run one revalidation pass, persist state, return process exit code."""
    pool = await get_supabase_pool()
    execution_id = uuid.uuid4()
    started = datetime.now(tz=timezone.utc)
    await update_system_status(
        pool,
        SERVICE,
        state="running",
        last_execution_id=execution_id,
        last_run_at=started,
    )
    try:
        stats = await _run(pool, execution_id)
        await update_system_status(
            pool,
            SERVICE,
            state="completed",
            last_stats=stats,
            last_error=None,
        )
        await append_log(
            pool,
            SERVICE,
            "success",
            f"{SERVICE} completed",
            meta=stats,
            execution_id=execution_id,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 -- top-level catch for systemd
        logger.exception(f"{SERVICE} failed")
        await update_system_status(
            pool, SERVICE, state="failed", last_error=str(exc)
        )
        await append_log(
            pool, SERVICE, "error", str(exc), execution_id=execution_id
        )
        return 1
    finally:
        await close_supabase_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
