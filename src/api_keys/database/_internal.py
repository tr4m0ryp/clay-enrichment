"""Shared helpers and whitelist constants for the database package.

jsonb convention -- ``validated_keys.capabilities`` is a DICT keyed by model
name, e.g. ``{"gemini-2.5-pro": {"is_accessible": true, ...}, ...}``. Both
the validator (Task 006) and the manager (Task 007) must produce/read this
exact shape so the pick query's jsonb path
``capabilities -> $model -> 'is_accessible'`` resolves. NEVER store
capabilities as a list.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.api_keys.types import KeyValidationResult, ValidationStatus


ALLOWED_SYSTEM_STATUS_FIELDS: frozenset[str] = frozenset(
    {
        "state",
        "active_tier",
        "tier_pro_exhausted_at",
        "tier_3_exhausted_at",
        "last_recovery_probe_at",
        "circuit_open_until",
        "last_execution_id",
        "last_run_at",
        "last_stats",
        "last_error",
        "last_query_index",
    }
)

ALLOWED_SERVICES: frozenset[str] = frozenset(
    {
        "scraper",
        "validator",
        "revalidator",
        "manager",
        "gemini_tier_manager",
        "recovery_probe",
        "quota_retest",
    }
)

AUTO_DISABLE_STATUS: ValidationStatus = "quota_reached"


def capabilities_to_dict(result: KeyValidationResult) -> dict[str, dict[str, Any]]:
    """Reshape a list[ModelCapability] into the jsonb dict-by-model.

    The downstream pick query indexes by ``capabilities -> <model_name>``,
    so every list of ModelCapability must become a model-keyed dict before
    being persisted.
    """
    out: dict[str, dict[str, Any]] = {}
    for cap in result.capabilities:
        out[cap.model_name] = {
            "is_accessible": cap.is_accessible,
            "response_time_ms": cap.response_time_ms,
            "error_code": cap.error_code,
            "error_message": cap.error_message,
            "max_tokens": cap.max_tokens,
            "features": cap.features,
        }
    return out


def encode_json(value: Any) -> Optional[str]:
    """Encode dict/list to JSON for jsonb columns; pass None through.

    asyncpg accepts text-cast jsonb (``$N::jsonb``) without a custom codec,
    which keeps the database module independent of pool configuration.
    """
    if value is None:
        return None
    return json.dumps(value)


def build_status_update(fields: dict[str, Any]) -> tuple[str, list[Any]]:
    """Filter ``fields`` against the whitelist and build a SET clause.

    Returns ``(set_clause, values)`` where set_clause uses placeholders
    starting at $2 (since $1 is reserved for the service primary key) and
    values is the matching ordered list of bound values. The ``last_stats``
    column is jsonb and gets an explicit ``::jsonb`` cast on its placeholder.
    """
    cols = [k for k in fields if k in ALLOWED_SYSTEM_STATUS_FIELDS]
    if not cols:
        return "", []
    set_parts: list[str] = []
    values: list[Any] = []
    for index, col in enumerate(cols):
        placeholder = f"${index + 2}"
        if col == "last_stats":
            set_parts.append(f"{col} = {placeholder}::jsonb")
            values.append(encode_json(fields[col]))
        else:
            set_parts.append(f"{col} = {placeholder}")
            values.append(fields[col])
    return ", ".join(set_parts), values
