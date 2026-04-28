"""Cron entrypoint: validate pending potential_keys rows.

Runs every 30 minutes via systemd timer. Pulls up to ``CLAY_VALIDATE_BATCH``
rows from potential_keys with validation_status='pending', validates each
against the three Gemini target models, upserts results into validated_keys,
and flips the source potential_keys row's validation_status. Persists run
state to the ``validator`` row in system_status.

Run as: ``python -m src.api_keys.cron.validate``
Tunable: ``CLAY_VALIDATE_BATCH`` env var (default 50).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

from src.api_keys.database import (
    append_log,
    get_pending_potential_keys,
    update_potential_key_status,
    update_system_status,
    upsert_validated_key,
)
from src.api_keys.supabase_client import close_supabase_pool, get_supabase_pool
from src.api_keys.validator import validate_gemini_key
from src.utils.logger import get_logger


logger = get_logger(__name__)
SERVICE = "validator"


async def _run(pool, execution_id: uuid.UUID) -> dict:
    """Validate one batch of pending potential_keys; return run stats."""
    batch = int(os.environ.get("CLAY_VALIDATE_BATCH", "50"))
    pending = await get_pending_potential_keys(pool, limit=batch)
    validated_count = 0
    invalid_count = 0
    for potential_key_id, key_value in pending:
        try:
            result = await validate_gemini_key(key_value, full=False)
            await upsert_validated_key(pool, potential_key_id, result)
            await update_potential_key_status(pool, potential_key_id, result.status)
            if result.is_valid:
                validated_count += 1
            else:
                invalid_count += 1
        except Exception as exc:  # noqa: BLE001 -- isolate per-key failures
            logger.exception(
                "validate failed for potential_key %s: %s", potential_key_id, exc
            )
            invalid_count += 1
    return {
        "validated": validated_count,
        "invalid": invalid_count,
        "total": len(pending),
    }


async def main() -> int:
    """Run one validation batch, persist state, return process exit code."""
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
