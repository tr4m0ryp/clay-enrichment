"""One-shot backfill: populate contacts.linkedin_url + contact_campaigns.linkedin_url
for existing high-priority leads (relevance_score >= 7) by calling Hunter
Email Finder. Skips rows that already have a non-empty linkedin_url.

Usage (on the GCP server):
    sudo /opt/clay-enrichment/.venv/bin/python /opt/clay-enrichment/scripts/backfill_linkedin.py

The email_resolver worker handles the steady state going forward; this
script exists to retrofit leads that were resolved before Hunter's
linkedin field was captured.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Allow running as a standalone script from anywhere on the server.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api_keys.supabase_client import get_supabase_pool  # noqa: E402
from src.config import get_config  # noqa: E402
from src.db.companies import CompaniesDB  # noqa: E402
from src.people.helpers import extract_domain, split_name  # noqa: E402
from src.people.pattern_lookup import PatternLookup  # noqa: E402

MIN_SCORE = 7


def _load_env() -> None:
    """Inject .env into os.environ so Config picks up keys when run via cron."""
    env_path = Path("/opt/clay-enrichment/.env")
    if not env_path.exists():
        env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


async def main() -> None:
    _load_env()
    config = get_config()
    if not config.hunter_api_key:
        print("HUNTER_API_KEY not set; aborting.")
        return

    pool = await get_supabase_pool()
    companies_db = CompaniesDB(pool)
    pattern_lookup = PatternLookup(config, companies_db)

    rows = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                cc.id           AS junction_id,
                cc.contact_id,
                c.name          AS contact_name,
                c.linkedin_url  AS contact_linkedin,
                co.website      AS company_website
            FROM contact_campaigns cc
            JOIN contacts c   ON cc.contact_id = c.id
            LEFT JOIN companies co ON cc.company_id = co.id
            WHERE cc.relevance_score >= $1
              AND (c.linkedin_url IS NULL OR c.linkedin_url = '')
            ORDER BY cc.relevance_score DESC
            """,
            MIN_SCORE,
        )

    print(f"Found {len(rows)} high-priority leads missing linkedin_url.")
    found = 0
    skipped = 0
    for row in rows:
        domain = extract_domain(row["company_website"] or "")
        if not domain or not row["contact_name"]:
            skipped += 1
            continue
        first, last = split_name(row["contact_name"])
        if not first:
            skipped += 1
            continue
        _, _, linkedin_url = await pattern_lookup.find_email(domain, first, last)
        if not linkedin_url:
            print(f"  no LinkedIn for {row['contact_name']} @ {domain}")
            continue
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE contacts SET linkedin_url = $1 WHERE id = $2",
                linkedin_url, row["contact_id"],
            )
            await conn.execute(
                "UPDATE contact_campaigns SET linkedin_url = $1 WHERE id = $2",
                linkedin_url, row["junction_id"],
            )
        found += 1
        print(f"  {row['contact_name']} @ {domain} -> {linkedin_url}")

    print(
        f"\nBackfill done: {found} populated, {skipped} skipped, "
        f"{len(rows) - found - skipped} no-result.",
    )


if __name__ == "__main__":
    asyncio.run(main())
