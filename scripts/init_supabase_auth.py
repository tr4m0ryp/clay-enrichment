"""Provision the Supabase Auth user for the Next.js dashboard. Idempotent.

Creates the operator login (default ``moussa@avelero.com``) via the Supabase
``auth.admin.create_user`` admin API. If the user already exists, the script
exits 0 -- "already" in the exception message is treated as a successful
no-op so re-runs on a seeded project remain safe.

Reads:
    SUPABASE_URL                -- required
    SUPABASE_SERVICE_ROLE_KEY   -- required (service-role JWT)
    MOUSSA_EMAIL                -- optional, defaults to moussa@avelero.com
    MOUSSA_PASSWORD             -- required
"""

from __future__ import annotations

import os
import sys

from supabase import create_client


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars required",
            file=sys.stderr,
        )
        return 1

    email = os.environ.get("MOUSSA_EMAIL", "moussa@avelero.com")
    password = os.environ.get("MOUSSA_PASSWORD")
    if not password:
        print("MOUSSA_PASSWORD env var required", file=sys.stderr)
        return 1

    sb = create_client(url, key)
    try:
        sb.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
            }
        )
        print(f"created user {email}")
        return 0
    except Exception as e:  # noqa: BLE001 - admin API surfaces broad errors
        # Most likely "User already registered" -- treat as success.
        if "already" in str(e).lower():
            print(f"user {email} already exists")
            return 0
        print(f"failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
