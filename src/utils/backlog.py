"""High-priority backlog counter -- shared by discovery + people backpressure.

A "high-priority lead" is a contact_campaigns junction row where both the
contact's relevance_score and the company's company_fit_score reached the
MIN_RESOLVE_SCORE bar (>=7) but no email has been generated yet
(email_subject IS NULL or empty). This is the count the resolver +
email-gen workers need to drain. When it sits above the configured
threshold, discovery and people skip their cycle so the funnel can
catch up instead of piling on more work.
"""

from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)

_BACKLOG_SQL = """
SELECT COUNT(*)
FROM contact_campaigns
WHERE relevance_score >= 7
  AND company_fit_score >= 7
  AND (email_subject IS NULL OR email_subject = '')
"""


async def count_high_priority_backlog(pool: asyncpg.Pool) -> int:
    """Return the number of high-priority leads not yet email-generated.

    Returns 0 on any DB error so backpressure failures never block the
    pipeline. The caller should log the result; this helper stays quiet.
    """
    try:
        async with pool.acquire() as conn:
            return int(await conn.fetchval(_BACKLOG_SQL) or 0)
    except Exception:
        logger.exception("count_high_priority_backlog failed; treating as 0")
        return 0
