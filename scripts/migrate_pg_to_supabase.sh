#!/usr/bin/env bash
# migrate_pg_to_supabase.sh -- pg_dump from local GCP Postgres -> psql import
# into Supabase. Operator-facing runbook helper, NOT invoked from any service.
#
# IMPORTANT (2026-04-28): The original GCP Postgres on the old
# "marketing-team-not-needed" project is unreachable -- billing has been
# closed on that project. This script is preserved for completeness, but the
# data migration it describes is essentially N/A for this cutover. The
# Supabase tables will be populated through normal app usage from now on.
#
# Run on a workstation with both DBs reachable. Idempotent: TRUNCATEs target
# tables before insert, so re-runs replace rather than duplicate.
set -euo pipefail

: "${PG_LOCAL_URL:?set PG_LOCAL_URL=postgresql://clay:...@localhost:5432/clay_enrichment}"
: "${SUPABASE_DB_URL:?set SUPABASE_DB_URL=postgresql://postgres.<ref>:...@db.<ref>.supabase.co:5432/postgres}"

DUMP=/tmp/clay_enrichment_data.sql

echo "[1/3] dumping data-only from local Postgres ..."
pg_dump --data-only --no-owner --no-privileges \
  --table=campaigns --table=companies --table=contacts --table=emails \
  --table=contact_campaigns --table=company_campaigns --table=contact_campaign_links \
  --table=settings \
  "$PG_LOCAL_URL" > "$DUMP"

echo "[2/3] truncating target tables in Supabase ..."
psql "$SUPABASE_DB_URL" -c "
  TRUNCATE contact_campaign_links, contact_campaigns, company_campaigns,
           emails, contacts, companies, campaigns, settings RESTART IDENTITY CASCADE;
"

echo "[3/3] importing data into Supabase ..."
psql "$SUPABASE_DB_URL" -f "$DUMP"

echo "done."
