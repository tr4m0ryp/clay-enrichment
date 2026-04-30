"""Shared dataclasses and literal type aliases for the api_keys subsystem.

All datetimes are timezone-aware (UTC). All UUIDs are uuid.UUID instances.
Mirrors FrogBytes_V3/lib/api-keys/types.ts with the additions called out in
notes/gemini-scraper-supabase-db-refactor.md (scraper, validator, github tokens).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID


ValidationStatus = Literal[
    "pending",
    "valid",
    "invalid",
    "quota_reached",
    "quota_exceeded",
    "embedding_only",
]

# Tier names recognized by the manager. 2.5-pro is kept in the Literal
# for backward-compat with legacy system_status rows but is excluded
# from TIER_LADDER below: free-tier limit:0 means it never serves a
# request, so descending through it just wastes a probe.
TierName = Literal[
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

# Tier ladder ordered by observed key coverage in our pool. As of
# 13.5k validated / 5 generate-valid: 3.1-flash-lite-preview leads
# at 5/5 coverage and ~1000 RPD/key. 2.5-pro is excluded -- free-tier
# limit:0 means it never serves a request. 2.0-flash{,-lite} are tail
# tiers in case some older keys retain 2.0-tier quota allocation.
TIER_LADDER: list[TierName] = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    # gemini-2.0-flash and gemini-2.0-flash-lite are excluded: free-tier
    # quota for both is limit:0 -- no key can ever serve a request on
    # those models. Including them in the ladder caused the pool to
    # descend to a broken bottom rung whenever upper-tier keys were
    # transiently cooling down. Re-add only if we ever pool keys whose
    # 2.0-tier access is actually nonzero.
]


@dataclass(slots=True)
class ScrapeMetadata:
    repository: Optional[str] = None
    filename: Optional[str] = None
    language: Optional[str] = None
    last_modified: Optional[str] = None


@dataclass(slots=True)
class ScrapedKey:
    key: str
    source_url: str
    found_at: datetime
    metadata: ScrapeMetadata
    source: Literal["github"] = "github"


@dataclass(slots=True)
class ScrapeProgress:
    total: int = 0
    processed: int = 0
    found: int = 0
    duplicates: int = 0
    validated: int = 0
    validation_errors: int = 0
    current_source: str = ""
    start_time: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


@dataclass(slots=True)
class ModelCapability:
    model_name: str
    is_accessible: bool
    response_time_ms: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    max_tokens: Optional[int] = None
    features: Optional[list[str]] = None
    # Set when a 429 response is received with parseable rate-limit metadata.
    # retry_after_seconds is the "Please retry in Xs" value from the error body
    # (or the Retry-After header). quota_limit is the "limit: N" from the
    # error body, used to distinguish project-frozen-on-this-model
    # (limit=0, no recovery) from per-minute throttles (limit>0, recovery
    # in retry_after_seconds).
    retry_after_seconds: Optional[float] = None
    quota_limit: Optional[int] = None


@dataclass(slots=True)
class RateLimitInfo:
    requests_per_minute: Optional[int] = None
    requests_per_day: Optional[int] = None


@dataclass(slots=True)
class KeyValidationResult:
    key: str
    is_valid: bool
    validated_at: datetime
    capabilities: list[ModelCapability]
    total_models_accessible: int
    total_models_tested: int
    average_response_time_ms: Optional[float]
    quota_remaining: Optional[int]
    rate_limit_info: Optional[RateLimitInfo]
    status: ValidationStatus


@dataclass(slots=True)
class CapabilitySummary:
    has_pro: bool
    has_3_flash_preview: bool
    has_25_flash: bool
    accessible_models: list[str]


@dataclass(slots=True)
class GitHubToken:
    id: UUID
    token_name: str
    token_value: str
    rate_limit_remaining: Optional[int] = None
    rate_limit_reset_at: Optional[datetime] = None
