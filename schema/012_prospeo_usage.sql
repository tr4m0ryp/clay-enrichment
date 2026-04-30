-- 012_prospeo_usage.sql
-- Track every Prospeo enrich-person call that consumes a credit, so the
-- dashboard can render a "X / 1500 used this month" progress bar.
--
-- Per Prospeo's pricing:
--   * 1 credit per match (email + linkedin + person + company)
--   * 10 credits per match when enrich_mobile=true
--   * 0 credits when free_enrichment=true (account-lifetime dedup of
--     a previously enriched record)
--   * 0 credits on NO_MATCH / INVALID_DATAPOINTS / 401 / 429
-- We log only the credit-spending calls; misses are off-budget.

BEGIN;

CREATE TABLE IF NOT EXISTS prospeo_usage (
    id           BIGSERIAL PRIMARY KEY,
    used_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    key_prefix   TEXT,         -- redacted "pk_xxx...yyy" for forensics
    credits      SMALLINT NOT NULL DEFAULT 1,
    contact_id   UUID,         -- optional, for cross-referencing leads
    domain       TEXT,         -- target company domain
    free_dedup   BOOLEAN NOT NULL DEFAULT false
);

-- used_at index serves both the dashboard query (filter by month) and
-- ad-hoc time-window slicing. Postgres rejects to_char(...) as a
-- generated-column expression because to_char is STABLE not
-- IMMUTABLE, so we keep the bucket implicit and query by range.
CREATE INDEX IF NOT EXISTS prospeo_usage_used_at
    ON prospeo_usage (used_at DESC);

COMMIT;
