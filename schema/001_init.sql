-- 001_init.sql -- Postgres schema for clay-enrichment pipeline
-- Replaces the Notion database structure with 5 main tables,
-- 2 join tables, indexes, CHECK constraints, and an auto-updated_at trigger.

BEGIN;

-- ---------------------------------------------------------------------------
-- Trigger function: auto-update updated_at on every UPDATE
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- 1. campaigns
-- ---------------------------------------------------------------------------
CREATE TABLE campaigns (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL UNIQUE,
    target_description TEXT NOT NULL DEFAULT '',
    status      TEXT        NOT NULL DEFAULT 'Active'
                            CHECK (status IN ('Active', 'Paused', 'Completed', 'Abort')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_campaigns_updated_at
    BEFORE UPDATE ON campaigns
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 2. companies
-- ---------------------------------------------------------------------------
CREATE TABLE companies (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT        NOT NULL,
    website         TEXT,
    industry        TEXT        CHECK (industry IN ('Fashion', 'Streetwear', 'Lifestyle', 'Other')),
    location        TEXT,
    size            TEXT,
    dpp_fit_score   INTEGER,
    status          TEXT        NOT NULL DEFAULT 'Discovered'
                                CHECK (status IN ('Discovered', 'Enriched', 'Partially Enriched', 'Contacts Found')),
    source_query    TEXT,
    body            TEXT        NOT NULL DEFAULT '',
    last_enriched_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 3. contacts
-- ---------------------------------------------------------------------------
CREATE TABLE contacts (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT        NOT NULL,
    job_title       TEXT,
    email           TEXT,
    email_verified  BOOLEAN     NOT NULL DEFAULT false,
    linkedin_url    TEXT,
    company_id      UUID        REFERENCES companies(id) ON DELETE SET NULL,
    status          TEXT        NOT NULL DEFAULT 'Found'
                                CHECK (status IN ('Found', 'Enriched', 'Researched', 'Email Generated')),
    context         TEXT,
    body            TEXT        NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_contacts_updated_at
    BEFORE UPDATE ON contacts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 4. emails
-- ---------------------------------------------------------------------------
CREATE TABLE emails (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subject         TEXT        NOT NULL,
    contact_id      UUID        REFERENCES contacts(id) ON DELETE SET NULL,
    campaign_id     UUID        REFERENCES campaigns(id) ON DELETE SET NULL,
    status          TEXT        NOT NULL DEFAULT 'Pending Review'
                                CHECK (status IN ('Pending Review', 'Approved', 'Sent', 'Rejected', 'Failed')),
    sender_address  TEXT,
    body            TEXT        NOT NULL DEFAULT '',
    bounce          BOOLEAN     NOT NULL DEFAULT false,
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_emails_updated_at
    BEFORE UPDATE ON emails
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 5. contact_campaigns (denormalized junction)
-- ---------------------------------------------------------------------------
CREATE TABLE contact_campaigns (
    id                   UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id           UUID    NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    campaign_id          UUID    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    company_id           UUID    REFERENCES companies(id) ON DELETE SET NULL,
    name                 TEXT    NOT NULL,
    job_title            TEXT,
    company_name         TEXT,
    email                TEXT,
    email_verified       BOOLEAN NOT NULL DEFAULT false,
    linkedin_url         TEXT,
    industry             TEXT,
    location             TEXT,
    company_fit_score    REAL,
    relevance_score      REAL,
    score_reasoning      TEXT,
    personalized_context TEXT,
    context              TEXT,
    email_subject        TEXT,
    outreach_status      TEXT    NOT NULL DEFAULT 'New'
                                 CHECK (outreach_status IN (
                                     'New', 'Email Pending Review', 'Email Approved',
                                     'Sent', 'Replied', 'Meeting Booked'
                                 )),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (contact_id, campaign_id)
);

CREATE TRIGGER trg_contact_campaigns_updated_at
    BEFORE UPDATE ON contact_campaigns
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Join table: company_campaigns (many-to-many)
-- ---------------------------------------------------------------------------
CREATE TABLE company_campaigns (
    company_id  UUID REFERENCES companies(id) ON DELETE CASCADE,
    campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    PRIMARY KEY (company_id, campaign_id)
);

-- ---------------------------------------------------------------------------
-- Join table: contact_campaign_links (many-to-many)
-- ---------------------------------------------------------------------------
CREATE TABLE contact_campaign_links (
    contact_id  UUID REFERENCES contacts(id) ON DELETE CASCADE,
    campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    PRIMARY KEY (contact_id, campaign_id)
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX idx_companies_status         ON companies(status);
CREATE INDEX idx_companies_name           ON companies(name);
CREATE INDEX idx_companies_last_enriched  ON companies(last_enriched_at);
CREATE INDEX idx_contacts_status          ON contacts(status);
CREATE INDEX idx_contacts_email           ON contacts(email);
CREATE INDEX idx_contacts_company         ON contacts(company_id);
CREATE INDEX idx_emails_status            ON emails(status);
CREATE INDEX idx_emails_campaign          ON emails(campaign_id);
CREATE INDEX idx_contact_campaigns_campaign ON contact_campaigns(campaign_id);
CREATE INDEX idx_contact_campaigns_contact  ON contact_campaigns(contact_id);
CREATE INDEX idx_contact_campaigns_scores   ON contact_campaigns(relevance_score, company_fit_score);

COMMIT;
