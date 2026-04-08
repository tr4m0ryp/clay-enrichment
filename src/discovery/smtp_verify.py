"""SMTP/MX email verification.

Checks whether an email address exists by resolving MX records and
performing SMTP RCPT TO probes. Never sends actual email.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_SMTP_TIMEOUT = 10
_RATE_LIMIT_INTERVAL = 1.0  # seconds between checks per domain
_HELO_DOMAIN = "verify.localhost"
_MAIL_FROM = "verify@localhost"


@dataclass
class VerifyResult:
    """Result of an email verification check."""

    email: str
    valid: bool
    method: str  # "mx_check", "smtp_rcpt", "catch_all", "unknown"
    confidence: str  # "high", "medium", "low"


class SMTPVerifier:
    """Verifies email addresses via MX lookup and SMTP RCPT TO.

    Rate-limits to max 1 request per second per domain. Uses a 10-second
    timeout for all network operations. Never sends actual email.
    """

    def __init__(self) -> None:
        """Initialize the verifier with an empty rate limit tracker."""
        self._domain_last_check: dict[str, float] = {}

    async def verify(self, email: str) -> VerifyResult:
        """Check if an email address exists via SMTP/MX lookup.

        Steps:
        1. Resolve MX records for the domain.
        2. Connect to the MX server and issue RCPT TO.
        3. Interpret the SMTP response code.
        4. Detect catch-all domains (low confidence).

        Args:
            email: The email address to verify.

        Returns:
            VerifyResult with validity, method used, and confidence level.
        """
        domain = email.split("@", 1)[-1].lower()

        await self._rate_limit(domain)

        # Step 1: MX lookup
        mx_hosts = await self._resolve_mx(domain)
        if not mx_hosts:
            logger.info("No MX records for domain: %s", domain)
            return VerifyResult(
                email=email,
                valid=False,
                method="mx_check",
                confidence="high",
            )

        # Step 2: SMTP RCPT TO check
        for mx_host in mx_hosts:
            result = await self._smtp_check(email, mx_host)
            if result is not None:
                return result

        # All MX hosts failed to respond usefully
        return VerifyResult(
            email=email,
            valid=False,
            method="unknown",
            confidence="low",
        )

    async def verify_batch(self, emails: list[str]) -> list[VerifyResult]:
        """Verify a list of email addresses sequentially.

        Respects per-domain rate limits between checks.

        Args:
            emails: List of email addresses to verify.

        Returns:
            List of VerifyResult objects in the same order as input.
        """
        results = []
        for email in emails:
            result = await self.verify(email)
            results.append(result)
        return results

    async def _rate_limit(self, domain: str) -> None:
        """Enforce per-domain rate limiting (max 1 check/sec).

        Args:
            domain: The email domain being checked.
        """
        now = time.monotonic()
        last = self._domain_last_check.get(domain, 0.0)
        elapsed = now - last
        if elapsed < _RATE_LIMIT_INTERVAL:
            await asyncio.sleep(_RATE_LIMIT_INTERVAL - elapsed)
        self._domain_last_check[domain] = time.monotonic()

    async def _resolve_mx(self, domain: str) -> list[str]:
        """Resolve MX records for a domain.

        Falls back to the domain itself if no MX records exist but
        the domain resolves to an A record.

        Args:
            domain: The domain to look up.

        Returns:
            List of MX hostnames sorted by priority, or empty list.
        """
        try:
            import dns.resolver

            loop = asyncio.get_event_loop()
            answers = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: dns.resolver.resolve(domain, "MX")
                ),
                timeout=_SMTP_TIMEOUT,
            )
            mx_records = []
            for rdata in answers:
                mx_records.append(
                    (rdata.preference, str(rdata.exchange).rstrip("."))
                )
            mx_records.sort(key=lambda x: x[0])
            return [host for _, host in mx_records]
        except ImportError:
            # dnspython not installed, fall back to socket
            return await self._resolve_mx_fallback(domain)
        except Exception:
            logger.debug(
                "MX resolution failed for %s, trying fallback", domain
            )
            return await self._resolve_mx_fallback(domain)

    async def _resolve_mx_fallback(self, domain: str) -> list[str]:
        """Fallback MX resolution using socket.getaddrinfo.

        If the domain has an A record, assume it handles its own mail.

        Args:
            domain: The domain to check.

        Returns:
            Single-element list with the domain, or empty list.
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
                timeout=_SMTP_TIMEOUT,
            )
            return [domain]
        except Exception:
            return []

    async def _smtp_check(
        self, email: str, mx_host: str
    ) -> VerifyResult | None:
        """Perform SMTP RCPT TO check against a specific MX host.

        Connects, sends HELO, MAIL FROM, and RCPT TO commands, then
        interprets the response. Also probes for catch-all behavior.

        Args:
            email: The email address to check.
            mx_host: The MX server hostname.

        Returns:
            VerifyResult if a determination was made, None if the host
            was unreachable or unresponsive.
        """
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(mx_host, 25),
                timeout=_SMTP_TIMEOUT,
            )
        except Exception:
            logger.debug("Cannot connect to MX host %s", mx_host)
            return None

        try:
            return await self._smtp_conversation(email, reader, writer)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _smtp_conversation(
        self,
        email: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> VerifyResult | None:
        """Run the SMTP conversation to check an address.

        Args:
            email: The email address to verify.
            reader: The asyncio stream reader for the SMTP connection.
            writer: The asyncio stream writer for the SMTP connection.

        Returns:
            VerifyResult if determination was made, None otherwise.
        """
        domain = email.split("@", 1)[-1]

        # Read banner
        banner = await self._read_response(reader)
        if not banner or not banner.startswith("2"):
            return None

        # HELO
        await self._send_command(writer, f"HELO {_HELO_DOMAIN}\r\n")
        helo_resp = await self._read_response(reader)
        if not helo_resp or not helo_resp.startswith("2"):
            return None

        # MAIL FROM
        await self._send_command(writer, f"MAIL FROM:<{_MAIL_FROM}>\r\n")
        mail_resp = await self._read_response(reader)
        if not mail_resp or not mail_resp.startswith("2"):
            return None

        # RCPT TO (actual address)
        await self._send_command(writer, f"RCPT TO:<{email}>\r\n")
        rcpt_resp = await self._read_response(reader)
        if not rcpt_resp:
            return None

        rcpt_code = rcpt_resp[:3]

        # Check for catch-all by testing a fake address
        is_catch_all = await self._check_catch_all(
            domain, reader, writer
        )

        # QUIT
        await self._send_command(writer, "QUIT\r\n")

        if rcpt_code == "250":
            if is_catch_all:
                return VerifyResult(
                    email=email,
                    valid=True,
                    method="catch_all",
                    confidence="low",
                )
            return VerifyResult(
                email=email,
                valid=True,
                method="smtp_rcpt",
                confidence="high",
            )
        elif rcpt_code.startswith("5"):
            return VerifyResult(
                email=email,
                valid=False,
                method="smtp_rcpt",
                confidence="high",
            )
        else:
            return VerifyResult(
                email=email,
                valid=False,
                method="unknown",
                confidence="medium",
            )

    async def _check_catch_all(
        self,
        domain: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> bool:
        """Detect if a domain is a catch-all (accepts any address).

        Sends RCPT TO with a random non-existent address. If the server
        accepts it, the domain is catch-all.

        Args:
            domain: The email domain.
            reader: SMTP stream reader.
            writer: SMTP stream writer.

        Returns:
            True if the domain appears to be catch-all.
        """
        fake_email = f"avelero-verify-nonexistent-xq9z@{domain}"
        try:
            await self._send_command(
                writer, f"RCPT TO:<{fake_email}>\r\n"
            )
            resp = await self._read_response(reader)
            if resp and resp.startswith("2"):
                logger.debug("Domain %s appears to be catch-all", domain)
                return True
        except Exception:
            pass
        return False

    async def _send_command(
        self, writer: asyncio.StreamWriter, command: str
    ) -> None:
        """Send an SMTP command.

        Args:
            writer: The asyncio stream writer.
            command: The SMTP command string (including CRLF).
        """
        writer.write(command.encode("ascii", errors="ignore"))
        await writer.drain()

    async def _read_response(self, reader: asyncio.StreamReader) -> str | None:
        """Read an SMTP response line with timeout.

        Args:
            reader: The asyncio stream reader.

        Returns:
            The response string, or None on timeout/error.
        """
        try:
            data = await asyncio.wait_for(
                reader.readline(), timeout=_SMTP_TIMEOUT
            )
            return data.decode("ascii", errors="ignore").strip()
        except Exception:
            return None
