"""Cron entrypoint: rapid retest of quota_exceeded keys.

Runs every 30 min via systemd timer. Pulls the oldest-validated
``quota_exceeded`` rows (those most likely to have crossed a quota
reset boundary since their last probe), revalidates with full=False,
and upserts. Keys that flip to ``valid`` become immediately pickable
by the manager; keys that flip to ``invalid`` no longer waste retest
cost on subsequent runs.

This sits between the per-scrape inline-validate and the once-daily
revalidate cron: it specifically targets the bucket of keys whose
probe outcome changes hour-to-hour with quota windows.

Run as: ``python -m src.api_keys.cron.quota_retest``
Tunable: ``CLAY_QUOTA_RETEST_BATCH`` env var (default 200).
"""

from __future__ import annotations

import asyncio
import os
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
SERVICE = "quota_retest"

_SELECT_OLDEST_QUOTA_SQL = """
    select id, potential_key_id, key_value
    from validated_keys
    where status = 'quota_exceeded'
    order by validated_at asc nulls first
    limit $1
"""


async def _run(pool, execution_id: uuid.UUID) -> dict:
    """Retest the oldest N quota_exceeded keys; return per-status counts."""
    batch = int(os.environ.get("CLAY_QUOTA_RETEST_BATCH", "200"))
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SELECT_OLDEST_QUOTA_SQL, batch)
    flipped_valid = 0
    still_quota = 0
    flipped_invalid = 0
    other = 0
    failed = 0
    for row in rows:
        try:
            result = await validate_gemini_key(row["key_value"])
            await upsert_validated_key(pool, row["potential_key_id"], result)
            if result.status == "valid":
                flipped_valid += 1
            elif result.status == "quota_exceeded":
                still_quota += 1
            elif result.status == "invalid":
                flipped_invalid += 1
            else:
                other += 1
        except Exception as exc:  # noqa: BLE001 -- isolate per-key failures
            failed += 1
            logger.exception("quota_retest failed for %s: %s", row["id"], exc)
    return {
        "flipped_valid": flipped_valid,
        "still_quota": still_quota,
        "flipped_invalid": flipped_invalid,
        "other": other,
        "failed": failed,
        "total": len(rows),
    }


async def main() -> int:
    """Run one quota-retest pass, persist state, return process exit code."""
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
