"""SMTPVerifier orchestrator with per-domain rate limiting."""

from __future__ import annotations

import asyncio
import logging
import time

from src.discovery.smtp_verify.mx import resolve_mx
from src.discovery.smtp_verify.protocol import smtp_check
from src.discovery.smtp_verify.types import RATE_LIMIT_INTERVAL, VerifyResult

logger = logging.getLogger(__name__)


class SMTPVerifier:
    """Verifies email addresses via MX lookup and SMTP RCPT TO.

    Rate-limits to max 1 request per second per domain. Uses a 3-second
    timeout for all network operations. Never sends actual email.
    """

    def __init__(self) -> None:
        self._domain_last_check: dict[str, float] = {}

    async def verify(self, email: str) -> VerifyResult:
        """Check if an email address exists via SMTP/MX lookup."""
        domain = email.split("@", 1)[-1].lower()
        await self._rate_limit(domain)

        mx_hosts = await resolve_mx(domain)
        if not mx_hosts:
            logger.info("No MX records for domain: %s", domain)
            return VerifyResult(
                email=email, valid=False, method="mx_check", confidence="high",
            )

        for mx_host in mx_hosts:
            result = await smtp_check(email, mx_host)
            if result is not None:
                return result

        return VerifyResult(
            email=email, valid=False, method="unknown", confidence="low",
        )

    async def verify_batch(self, emails: list[str]) -> list[VerifyResult]:
        """Verify a list of email addresses sequentially."""
        results = []
        for email in emails:
            result = await self.verify(email)
            results.append(result)
        return results

    async def _rate_limit(self, domain: str) -> None:
        """Enforce per-domain rate limiting (max 1 check/sec)."""
        now = time.monotonic()
        last = self._domain_last_check.get(domain, 0.0)
        elapsed = now - last
        if elapsed < RATE_LIMIT_INTERVAL:
            await asyncio.sleep(RATE_LIMIT_INTERVAL - elapsed)
        self._domain_last_check[domain] = time.monotonic()
