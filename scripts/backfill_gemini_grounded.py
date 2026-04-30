"""One-shot: run the Gemini grounded fallback on every contact whose
prospeo_status is currently 'not_found'.

Bypasses the 6h resolver cooldown so you don't have to wait for the
natural pickup. Persists the same way the live resolver does:
  - email -> contacts.email + contact_campaigns.email
  - linkedin_url -> contacts.linkedin_url + contact_campaigns.linkedin_url
  - email_verified flag set when MyEmailVerifier accepts the address

Logs every call (hit or miss) to gemini_finder_usage so the dashboard
counter and the per-contact cooldown stay accurate.

Usage on the GCP server:
    sudo /opt/clay-enrichment/.venv/bin/python \
        /opt/clay-enrichment/scripts/backfill_gemini_grounded.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    env = Path("/opt/clay-enrichment/.env")
    if not env.exists():
        env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


_load_env()

# Lazy imports so _load_env runs before src.config picks up env.
from src.api_keys.supabase_client import get_supabase_pool  # noqa: E402
from src.config import get_config  # noqa: E402
from src.db.contacts import ContactsDB  # noqa: E402
from src.gemini.client import GeminiClient  # noqa: E402
from src.people.email_verifier_api import MyEmailVerifierClient  # noqa: E402
from src.people.gemini_grounded_finder import GeminiGroundedFinder  # noqa: E402
from src.people.helpers import extract_domain  # noqa: E402
from src.people.smtp_verify import SMTPVerifier  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("backfill_gemini")


async def main() -> None:
    config = get_config()
    pool = await get_supabase_pool()
    contacts_db = ContactsDB(pool)
    gemini_client = GeminiClient(config=config)

    # Pick the verifier the pipeline already uses.
    if config.myemailverifier_api_key:
        smtp_verifier = MyEmailVerifierClient(
            config.myemailverifier_api_key,
        )
    else:
        smtp_verifier = SMTPVerifier()

    finder = GeminiGroundedFinder(
        gemini_client=gemini_client, usage_pool=pool,
    )

    rows = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                cc.id           AS junction_id,
                cc.contact_id,
                cc.linkedin_url AS existing_linkedin,
                c.name          AS contact_name,
                c.job_title,
                co.name         AS company_name,
                co.website      AS company_website
            FROM contact_campaigns cc
            JOIN contacts c   ON c.id  = cc.contact_id
            LEFT JOIN companies co ON co.id = cc.company_id
            WHERE cc.relevance_score >= 7
              AND (cc.email IS NULL OR cc.email = '')
              AND cc.updated_at > cc.created_at + interval '1 second'
              AND NOT EXISTS (
                  SELECT 1 FROM gemini_finder_usage gu
                  WHERE gu.contact_id = cc.contact_id
                    AND gu.used_at >= now() - interval '7 days'
              )
            ORDER BY cc.relevance_score DESC, cc.created_at ASC
            """,
        )

    logger.info(
        "backfill_gemini: %d not_found contacts to attempt",
        len(rows),
    )
    hits = 0
    for row in rows:
        contact_id = str(row["contact_id"]) if row["contact_id"] else None
        contact_name = row["contact_name"] or ""
        domain = extract_domain(row["company_website"] or "")
        if not contact_id or not contact_name or not domain:
            continue
        try:
            ctx = await contacts_db.get_body(contact_id)
        except Exception:
            ctx = ""

        result = await finder.find(
            contact_id=contact_id,
            contact_name=contact_name,
            job_title=row["job_title"] or "",
            company_name=row["company_name"] or "",
            company_website=row["company_website"] or "",
            domain=domain,
            context=ctx,
        )
        if result is None:
            logger.info("  miss: %s @ %s", contact_name, domain)
            continue

        # Persist linkedin first (it's free, always safe)
        contact_fields: dict[str, object] = {}
        cc_set: list[tuple[str, object]] = []
        if result.linkedin_url:
            contact_fields["linkedin_url"] = result.linkedin_url
            cc_set.append(("linkedin_url", result.linkedin_url))

        # Verify email through MyEmailVerifier before persisting
        if result.email:
            try:
                verify_res = await smtp_verifier.verify(result.email)
                verified = bool(getattr(verify_res, "valid", False))
            except Exception:
                verified = False
            if verified:
                contact_fields["email"] = result.email
                contact_fields["email_verified"] = True
                cc_set.extend([
                    ("email", result.email),
                    ("email_verified", True),
                ])
                logger.info(
                    "  HIT: %s @ %s -> email=%s linkedin=%s",
                    contact_name, domain, result.email,
                    result.linkedin_url or "(none)",
                )
                hits += 1
            else:
                logger.info(
                    "  partial: %s @ %s -> linkedin=%s "
                    "(email %s did not verify)",
                    contact_name, domain,
                    result.linkedin_url or "(none)",
                    result.email,
                )
        elif result.linkedin_url:
            logger.info(
                "  partial: %s @ %s -> linkedin=%s (no email)",
                contact_name, domain, result.linkedin_url,
            )

        if contact_fields:
            try:
                await contacts_db.update_contact(contact_id, **contact_fields)
            except Exception:
                logger.exception(
                    "  failed to update contact %s", contact_id,
                )
        if cc_set:
            cols = ", ".join(f"{k} = ${i+1}" for i, (k, _) in enumerate(cc_set))
            vals = [v for _, v in cc_set]
            vals.append(row["junction_id"])
            sql = (
                f"UPDATE contact_campaigns SET {cols}, updated_at = now() "
                f"WHERE id = ${len(vals)}::uuid"
            )
            try:
                async with pool.acquire() as conn:
                    await conn.execute(sql, *vals)
            except Exception:
                logger.exception(
                    "  failed to update junction %s", row["junction_id"],
                )

    logger.info("backfill_gemini: %d/%d hits", hits, len(rows))


if __name__ == "__main__":
    asyncio.run(main())
