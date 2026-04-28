"""Cron entrypoint: probe upward for tier recovery.

Runs every 4 hours via systemd timer. One call to KeyPoolManager.recovery_probe()
attempts to flip the tier ladder back up after pro/preview cooldowns. Persists
run state to the ``recovery_probe`` row in system_status (allowed by the
service whitelist in src/api_keys/database/_internal.py).

Run as: ``python -m src.api_keys.cron.recovery_probe``
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone

from src.api_keys.database import append_log, update_system_status
from src.api_keys.manager import KeyPoolManager
from src.api_keys.supabase_client import close_supabase_pool, get_supabase_pool
from src.utils.logger import get_logger


logger = get_logger(__name__)
SERVICE = "recovery_probe"


async def _run(pool, execution_id: uuid.UUID) -> dict:
    """One recovery_probe pass; returns whether any tier flipped up."""
    manager = KeyPoolManager(pool)
    flipped = await manager.recovery_probe()
    return {"tier_flipped_up": flipped}


async def main() -> int:
    """Run one recovery probe, persist state, return process exit code."""
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
