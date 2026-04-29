-- 009_redesign_2026_04_29.sql
-- Schema additions for the 2026-04-29 redesign (research/campaign_creation_redesign.md)
-- Adds:
--   campaigns: email_style_profile, sample_email_subject, sample_email_body,
--              icp_brief, banned_phrases, discovery_strategy_index
--   companies: email_pattern, email_pattern_source

BEGIN;

-- Campaign-level cold-email style + ICP brief (populated by the Next-button flow)
ALTER TABLE campaigns
    ADD COLUMN email_style_profile  TEXT  NOT NULL DEFAULT '',
    ADD COLUMN sample_email_subject TEXT,
    ADD COLUMN sample_email_body    TEXT,
    ADD COLUMN icp_brief            TEXT  NOT NULL DEFAULT '',
    ADD COLUMN banned_phrases       JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN discovery_strategy_index INTEGER NOT NULL DEFAULT 0;

-- Per-company cached email pattern (Hunter Domain Search result + provenance)
ALTER TABLE companies
    ADD COLUMN email_pattern        TEXT,
    ADD COLUMN email_pattern_source TEXT;

-- Optional CHECK on the source column to keep the value space tight
ALTER TABLE companies
    ADD CONSTRAINT companies_email_pattern_source_check
    CHECK (email_pattern_source IS NULL
           OR email_pattern_source IN ('hunter', 'opensource', 'gemini', 'none'));

COMMIT;

-- Apply on server: psql "$DATABASE_URL" -f schema/009_redesign_2026_04_29.sql
