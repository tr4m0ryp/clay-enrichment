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
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
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
