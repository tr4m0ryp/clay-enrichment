"""SMTP RCPT TO probe and catch-all detection.

Implements the conversation against an MX host: HELO, MAIL FROM, RCPT TO,
plus a follow-up RCPT TO with a random local-part to detect catch-all.
"""

from __future__ import annotations

import asyncio
import logging

from src.people.smtp_verify.types import (
    HELO_DOMAIN,
    MAIL_FROM,
    SMTP_TIMEOUT,
    VerifyResult,
)

logger = logging.getLogger(__name__)


async def smtp_check(email: str, mx_host: str) -> VerifyResult | None:
    """Open a connection to mx_host and run the RCPT TO probe.

    Returns a VerifyResult, or None if the host was unreachable/unresponsive.
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(mx_host, 25),
            timeout=SMTP_TIMEOUT,
        )
    except Exception:
        logger.debug("Cannot connect to MX host %s", mx_host)
        return None

    try:
        return await _smtp_conversation(email, reader, writer)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _smtp_conversation(
    email: str,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> VerifyResult | None:
    """Run HELO -> MAIL FROM -> RCPT TO -> catch-all probe -> QUIT."""
    domain = email.split("@", 1)[-1]

    banner = await _read_response(reader)
    if not banner or not banner.startswith("2"):
        return None

    await _send_command(writer, f"HELO {HELO_DOMAIN}\r\n")
    helo_resp = await _read_response(reader)
    if not helo_resp or not helo_resp.startswith("2"):
        return None

    await _send_command(writer, f"MAIL FROM:<{MAIL_FROM}>\r\n")
    mail_resp = await _read_response(reader)
    if not mail_resp or not mail_resp.startswith("2"):
        return None

    await _send_command(writer, f"RCPT TO:<{email}>\r\n")
    rcpt_resp = await _read_response(reader)
    if not rcpt_resp:
        return None

    rcpt_code = rcpt_resp[:3]
    is_catch_all = await _check_catch_all(domain, reader, writer)
    await _send_command(writer, "QUIT\r\n")

    if rcpt_code == "250":
        if is_catch_all:
            return VerifyResult(
                email=email, valid=True, method="catch_all", confidence="low",
            )
        return VerifyResult(
            email=email, valid=True, method="smtp_rcpt", confidence="high",
        )
    if rcpt_code.startswith("5"):
        return VerifyResult(
            email=email, valid=False, method="smtp_rcpt", confidence="high",
        )
    return VerifyResult(
        email=email, valid=False, method="unknown", confidence="medium",
    )


async def _check_catch_all(
    domain: str,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> bool:
    """Probe a random local-part. If accepted, the domain is catch-all."""
    fake_email = f"avelero-verify-nonexistent-xq9z@{domain}"
    try:
        await _send_command(writer, f"RCPT TO:<{fake_email}>\r\n")
        resp = await _read_response(reader)
        if resp and resp.startswith("2"):
            logger.debug("Domain %s appears to be catch-all", domain)
            return True
    except Exception:
        pass
    return False


async def _send_command(writer: asyncio.StreamWriter, command: str) -> None:
    writer.write(command.encode("ascii", errors="ignore"))
    await writer.drain()


async def _read_response(reader: asyncio.StreamReader) -> str | None:
    try:
        data = await asyncio.wait_for(
            reader.readline(), timeout=SMTP_TIMEOUT
        )
        return data.decode("ascii", errors="ignore").strip()
    except Exception:
        return None
