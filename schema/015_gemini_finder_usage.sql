-- 015_gemini_finder_usage.sql
-- Track every Gemini-grounded fallback call so the dashboard can
-- show "tried by Gemini" stats and the email_resolver can skip
-- contacts already attempted within the cooldown window.

BEGIN;

CREATE TABLE IF NOT EXISTS gemini_finder_usage (
    id              BIGSERIAL PRIMARY KEY,
    used_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    contact_id      UUID,
    domain          TEXT,
    found_email     BOOLEAN NOT NULL DEFAULT false,
    found_linkedin  BOOLEAN NOT NULL DEFAULT false,
    error           BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS gemini_finder_usage_used_at
    ON gemini_finder_usage (used_at DESC);

CREATE INDEX IF NOT EXISTS gemini_finder_usage_contact
    ON gemini_finder_usage (contact_id, used_at DESC);

COMMIT;
