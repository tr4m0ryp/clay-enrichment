"""Verification result type and shared SMTP constants."""

from __future__ import annotations

from dataclasses import dataclass


SMTP_TIMEOUT = 3
RATE_LIMIT_INTERVAL = 1.0  # seconds between checks per domain
HELO_DOMAIN = "verify.localhost"
MAIL_FROM = "verify@localhost"


@dataclass
class VerifyResult:
    """Result of an email verification check."""

    email: str
    valid: bool
    method: str  # "mx_check", "smtp_rcpt", "catch_all", "unknown"
    confidence: str  # "high", "medium", "low"
