"""Async DB primitives for the api_keys subsystem.

Wraps asyncpg queries over four Supabase tables produced by Task 001:
``potential_keys``, ``validated_keys``, ``key_pool_logs``, and
``system_status``. The github_tokens table is owned by Task 004
(src/api_keys/github_token_pool.py) and is intentionally not touched here.

jsonb convention -- ``validated_keys.capabilities`` is a DICT keyed by model
name, e.g. ``{"gemini-2.5-pro": {"is_accessible": true, ...}, ...}``. Both
the validator (Task 006) and the manager (Task 007) must produce/read this
exact shape so the pick query's jsonb path
``capabilities -> $model -> 'is_accessible'`` resolves. NEVER store
capabilities as a list.
"""

from src.api_keys.database.logs import append_log
from src.api_keys.database.potential import (
    get_existing_key_values,
    get_pending_potential_keys,
    insert_potential_key,
    insert_potential_keys_batch,
    update_potential_key_status,
)
from src.api_keys.database.status import get_system_status, update_system_status
from src.api_keys.database.validated import (
    get_active_validated_keys,
    increment_consecutive_failures,
    mark_validated_key_status,
    pick_validated_key,
    reset_consecutive_failures,
    update_validated_capability,
    upsert_validated_key,
)


__all__ = [
    "insert_potential_key",
    "insert_potential_keys_batch",
    "get_existing_key_values",
    "get_pending_potential_keys",
    "update_potential_key_status",
    "upsert_validated_key",
    "pick_validated_key",
    "increment_consecutive_failures",
    "reset_consecutive_failures",
    "update_validated_capability",
    "mark_validated_key_status",
    "get_active_validated_keys",
    "append_log",
    "get_system_status",
    "update_system_status",
]
