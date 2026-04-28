"""Seed the GitHub PAT pool. Idempotent.

Reads PATs either from sequential env vars (``GITHUB_PAT_1``, ``GITHUB_PAT_2``,
...) or from a file with one PAT per line via ``--from-file``. Inserts each
PAT into the ``github_tokens`` table with ``ON CONFLICT (token_value) DO
NOTHING`` so re-runs on already-seeded data are safe and exit 0.

Usage:
    GITHUB_PAT_1=... GITHUB_PAT_2=... python scripts/init_github_tokens.py
    python scripts/init_github_tokens.py --from-file pats.txt

Requires: SUPABASE_DB_URL set in env (used by ``get_supabase_pool``).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from src.api_keys.supabase_client import close_supabase_pool, get_supabase_pool


INSERT_SQL = """
INSERT INTO github_tokens (token_name, token_value, is_active)
VALUES ($1, $2, true)
ON CONFLICT (token_value) DO NOTHING
RETURNING id;
"""


def _load_pats_from_file(path: str) -> list[str]:
    with open(path) as fh:
        return [line.strip() for line in fh if line.strip()]


def _load_pats_from_env() -> list[str]:
    pats: list[str] = []
    i = 1
    while True:
        v = os.environ.get(f"GITHUB_PAT_{i}")
        if not v:
            break
        pats.append(v)
        i += 1
    return pats


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-file",
        dest="from_file",
        help="Path to a file containing one PAT per line",
    )
    args = parser.parse_args()

    if args.from_file:
        pats = _load_pats_from_file(args.from_file)
    else:
        pats = _load_pats_from_env()

    if not pats:
        print("no PATs found in env or file", file=sys.stderr)
        return 1

    pool = await get_supabase_pool()
    inserted = 0
    skipped = 0
    try:
        async with pool.acquire() as conn:
            for idx, pat in enumerate(pats, start=1):
                row = await conn.fetchrow(INSERT_SQL, f"pat-{idx}", pat)
                if row:
                    inserted += 1
                else:
                    skipped += 1
    finally:
        await close_supabase_pool()

    print(f"inserted={inserted} skipped={skipped} total={len(pats)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
