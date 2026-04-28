"""MX record resolution with dnspython, falling back to socket lookups."""

from __future__ import annotations

import asyncio
import logging
import socket

from src.people.smtp_verify.types import SMTP_TIMEOUT

logger = logging.getLogger(__name__)


async def resolve_mx(domain: str) -> list[str]:
    """Resolve MX records for a domain.

    Falls back to the domain itself if no MX records exist but the
    domain still resolves to an A record.

    Returns MX hostnames sorted by preference (lowest first), or [].
    """
    try:
        import dns.resolver

        loop = asyncio.get_event_loop()
        answers = await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: dns.resolver.resolve(domain, "MX")
            ),
            timeout=SMTP_TIMEOUT,
        )
        mx_records = []
        for rdata in answers:
            mx_records.append(
                (rdata.preference, str(rdata.exchange).rstrip("."))
            )
        mx_records.sort(key=lambda x: x[0])
        return [host for _, host in mx_records]
    except ImportError:
        return await _resolve_mx_fallback(domain)
    except Exception:
        logger.debug("MX resolution failed for %s, trying fallback", domain)
        return await _resolve_mx_fallback(domain)


async def _resolve_mx_fallback(domain: str) -> list[str]:
    """Fallback MX resolution using socket.getaddrinfo.

    If the domain has an A record, assume it handles its own mail.
    """
    loop = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: socket.getaddrinfo(
                    domain, 25, socket.AF_INET, socket.SOCK_STREAM
                ),
            ),
            timeout=SMTP_TIMEOUT,
        )
        return [domain]
    except Exception:
        return []
